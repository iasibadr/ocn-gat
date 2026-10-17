import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ocn_core.agent_integration import prepare, PinnedSynthesizer
from ocn_core.designer import instantiate
from ocn_core import gat


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.habitat=self.root/'docs';self.habitat.mkdir()
        self.text='Delivery Friday.';(self.habitat/'a.md').write_text(self.text)
        self.marker=self.root/'executed';self.source=self.root/'existing.py';self.instance=self.root/'agent'
        self.code=(f'from pathlib import Path\nPath({str(self.marker)!r}).write_text("executed")\n'
            'def build_synthesizer(model):\n'
            '    def synthesize(question, documents):\n'
            '        doc=documents[0]\n'
            '        return {"response":{"answer":doc["text"],"abstain":False,"citations":[{"document_id":doc["document_id"],"quote":doc["text"]}]},"usage":{"model":model}}\n'
            '    return synthesize\n')
        self.source.write_text(self.code)
        self.plan=dict(format='gat.document-plan.v1',habitat=str(self.habitat),mission='When?',runtime_model='existing-model',
            documents=[dict(document_id='d',path='a.md',sha256=hashlib.sha256(self.text.encode()).hexdigest())],
            abstain=False,rationale='Test fixture',designer_usage={})

    def adapt(self):
        return instantiate(self.instance,self.plan,integration=prepare(self.source))

    def test_copy_without_execution_and_relocation(self):
        self.adapt();self.assertFalse(self.marker.exists())
        (self.habitat/'moved').mkdir();(self.habitat/'a.md').rename(self.habitat/'moved/b.md')
        self.source.write_text('raise RuntimeError("Original was replaced")')
        result=gat.run(self.instance,model='operator-choice')
        self.assertEqual(result['answer'],self.text)
        self.assertEqual(result['usage']['model'],'operator-choice')
        self.assertEqual(result['citations'][0]['path'],'moved/b.md')
        self.assertTrue(self.marker.exists())
        self.assertEqual((self.instance/'agent.py').read_text(),self.code)

    def test_corruption_blocks_execution_without_fallback(self):
        self.adapt();(self.instance/'agent.py').write_text(self.code+'\n# changed\n')
        with self.assertRaisesRegex(ValueError,'code changed'):gat.run(self.instance)
        self.assertFalse(self.marker.exists())

    def test_pause_and_source_failure_precede_execution(self):
        self.adapt();gat.set_paused(self.instance,True)
        with self.assertRaises(RuntimeError):gat.run(self.instance)
        self.assertFalse(self.marker.exists())
        gat.set_paused(self.instance,False);(self.habitat/'a.md').write_text('Unauthorized update')
        with self.assertRaises(ValueError):gat.run(self.instance)
        self.assertFalse(self.marker.exists())

    def test_invalid_factory_and_oversize_rejected_before_create(self):
        for code in ('def build_synthesizer(a,b): return None', 'x'*65537, 'def broken('):
            self.source.write_text(code)
            with self.assertRaises(ValueError):self.adapt()
            self.assertFalse(self.instance.exists())

    def test_contract_failure_is_visible(self):
        self.source.write_text('def build_synthesizer(model):\n    return lambda question, documents: {"answer":"invented"}\n')
        self.adapt()
        with self.assertRaisesRegex(ValueError,'synthesis envelope'):gat.run(self.instance)

    def test_descriptor_cannot_disappear_silently(self):
        self.adapt();path=self.instance/'instance.json';config=json.loads(path.read_text())
        del config['integration'];path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError,'integration descriptor'):gat.run(self.instance)
        self.assertFalse(self.marker.exists())

    def test_executes_checked_bytes_not_reopened_file(self):
        config=self.adapt()
        bridge=PinnedSynthesizer(self.instance,config['integration'],'chosen')
        (self.instance/'agent.py').write_text('raise RuntimeError("Wrong bytes")')
        answer=bridge('When?',[dict(document_id='d',text=self.text)])
        self.assertEqual(answer['response']['answer'],self.text)

    def test_context_budget_precedes_module_execution(self):
        self.text='x'*17000;(self.habitat/'a.md').write_text(self.text)
        self.plan['documents'][0]['sha256']=hashlib.sha256(self.text.encode()).hexdigest()
        self.adapt()
        with self.assertRaisesRegex(ValueError,'context budget'):gat.run(self.instance)
        self.assertFalse(self.marker.exists())

if __name__=='__main__':unittest.main()
