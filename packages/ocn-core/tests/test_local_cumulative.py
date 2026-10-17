"""Real sandbox regression/adoption checks for retained local-repair contracts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.candidate_adoption import adopt,rollback
from ocn_core.local_repair import local_repair,variations
from ocn_core.hybrid_repair import hybrid_repair


def bridge(expression):
    return Integration(('def build_synthesizer(model):\n'
        '    def run(question, documents):\n'
        '        for d in documents:\n'
        '            if d["document_id"] == question:\n'
        f'                value = {expression}\n'
        '                return dict(response=dict(answer=value,abstain=False,citations=[dict(document_id=d["document_id"],quote=d["text"])]),usage={})\n'
        '        return dict(response=dict(answer="Unknown",abstain=True,citations=[]),usage={})\n'
        '    return run\n').encode(),'build_synthesizer')


def suite(ident,text,answer):
    return dict(format='gat.acceptance-suite.v1',cases=[dict(id=ident,question=ident,
        documents=[dict(document_id=ident,text=text)],expected=dict(response=dict(answer=answer,
        abstain=False,citations=[dict(document_id=ident,quote=text)])))])


class LocalCumulativeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.instance=self.root/'agent'
        docs=self.root/'docs';docs.mkdir();(docs/'a.md').write_text('ALPHA');(docs/'b.md').write_text(' BETA ')
        self.empty=Integration(b'def build_synthesizer(model):\n    return lambda question, documents: dict(response=dict(answer="Unknown",abstain=True,citations=[]),usage={})\n','build_synthesizer')
        gat.create(self.instance,docs,{'a':'a.md','b':'b.md'},'a',integration=self.empty,isolated=True)
        self.old=suite('a','ALPHA','alpha');self.new=suite('b',' BETA ',' BETA ')

    def bootstrap(self,expression):
        self.current=bridge(expression)
        self.assertTrue(adopt(self.instance,self.current,self.old,self.empty.descriptor()['sha256'])['adopted'])

    def test_global_normalization_removal_cannot_erase_retained_rule(self):
        self.bootstrap('d["text"].lower()')
        before=(self.instance/'instance.json').read_bytes()
        result=local_repair(self.instance,self.new,self.root/'audit',preserve_acceptance=True)
        self.assertEqual(result['status'],'no_passing_candidate')
        self.assertEqual((self.instance/'instance.json').read_bytes(),before)
        report=json.loads((self.root/'audit/candidate-0/evaluation.json').read_text())
        self.assertEqual((report['passed'],report['cases']),(1,2))

    def test_cli_adopts_only_change_preserving_old_rule(self):
        self.bootstrap('d["text"].lower() if question == "a" else d["text"].strip()')
        path=self.root/'suite.json';path.write_text(json.dumps(self.new))
        done=subprocess.run([sys.executable,'-m','ocn_core.gat','repair-local',str(self.instance),
            '--suite',str(path),'--output',str(self.root/'audit'),'--preserve-acceptance'],capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr)
        result=json.loads(done.stdout);self.assertTrue(result['adopted'])
        self.assertEqual(result['decision']['candidate']['cases'],2)
        self.assertEqual(gat.run(self.instance,question='a')['answer'],'alpha')
        self.assertEqual(gat.run(self.instance,question='b')['answer'],' BETA ')

    def test_missing_retained_evidence_stops_before_search(self):
        self.bootstrap('d["text"].lower()')
        config=json.loads((self.instance/'instance.json').read_text())
        (self.instance/'acceptance-suites'/(config['evolution']['suite_sha256']+'.json')).unlink()
        with patch('ocn_core.local_repair.variations') as search:
            with self.assertRaises(FileNotFoundError):
                local_repair(self.instance,self.new,self.root/'audit',preserve_acceptance=True)
            search.assert_not_called()
        self.assertFalse((self.root/'audit').exists())

    def test_same_source_rollback_roundtrip_invalidates_lineage(self):
        self.bootstrap('d["text"].lower() if question == "a" else d["text"].strip()')
        def raced(*args):
            result=rollback(self.instance,self.current.descriptor()['sha256'])
            rollback(self.instance,result['integration']['sha256'])
            return variations(*args)
        with patch('ocn_core.local_repair.variations',side_effect=raced):
            with self.assertRaisesRegex(ValueError,'lineage changed'):
                local_repair(self.instance,self.new,self.root/'audit',preserve_acceptance=True)
        self.assertEqual(json.loads((self.instance/'instance.json').read_text())['integration']['sha256'],self.current.descriptor()['sha256'])

    def test_hybrid_designer_fallback_also_preserves_old_rule(self):
        self.bootstrap('d["text"].lower()')
        proposer=Mock(return_value=(bridge('d["text"]'),dict(model_calls=0)))
        before=(self.instance/'instance.json').read_bytes()
        result=hybrid_repair(self.instance,'Preserve a normalization and b exact text.',self.new,proposer,
            self.root/'audit',preserve_acceptance=True)
        self.assertEqual(result['route'],'local_then_designer')
        self.assertEqual(result['status'],'rejected');proposer.assert_called_once()
        self.assertEqual(result['designer']['decision']['candidate']['cases'],2)
        self.assertEqual((self.instance/'instance.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
