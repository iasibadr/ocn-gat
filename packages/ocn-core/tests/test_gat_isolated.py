import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import prepare
from ocn_core.designer import instantiate


class IsolatedInstanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.text='Delivery Friday.';(self.docs/'a.md').write_text(self.text)
        self.source=self.root/'source.py'
        self.source.write_text('raise RuntimeError("Host execution forbidden")\ndef build_synthesizer(model): return None\n')
        self.integration=prepare(self.source);self.instance=self.root/'instance'

    def create(self):
        return gat.create(self.instance,self.docs,{'a':'a.md'},'When?',integration=self.integration,isolated=True)

    def result(self):
        return dict(status='completed',source_sha256=self.integration.descriptor()['sha256'],result=dict(
            response=dict(answer=self.text,abstain=False,citations=[dict(document_id='a',quote=self.text)]),usage={}))

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_reopened_manifest_keeps_isolation_and_pinned_bytes(self, run):
        self.create();run.return_value=self.result()
        self.source.write_text('raise RuntimeError("Changed source")')
        (self.docs/'a.md').rename(self.docs/'moved.md')
        answer=gat.run(str(self.instance))
        self.assertEqual(answer['citations'][0]['path'],'moved.md')
        self.assertEqual(answer['usage']['execution'],'offline_bubblewrap')
        self.assertEqual(run.call_args.args[0].source,self.integration.source)
        self.assertEqual(gat.status(self.instance)['format'],gat.ISOLATED_FORMAT)

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_corruption_and_pause_precede_execution(self, run):
        self.create();gat.set_paused(self.instance,True)
        with self.assertRaises(RuntimeError):gat.run(self.instance)
        gat.set_paused(self.instance,False)
        (self.instance/'agent.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'code changed'):gat.run(self.instance)
        run.assert_not_called()

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_failure_never_invokes_host_or_override(self, run):
        self.create();run.side_effect=RuntimeError('Bubblewrap required')
        with self.assertRaisesRegex(RuntimeError,'Bubblewrap'):gat.run(self.instance)
        with self.assertRaisesRegex(ValueError,'override'):gat.run(self.instance,synthesizer=lambda *a:None)
        self.assertEqual(run.call_count,1)

    def test_invalid_mode_or_missing_descriptor_rejected(self):
        with self.assertRaises(ValueError):gat.create(self.instance,self.docs,{'a':'a.md'},'When?',isolated=True)
        self.assertFalse(self.instance.exists())
        self.create();path=self.instance/'instance.json';config=json.loads(path.read_text())
        del config['integration'];path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError,'descriptor'):gat.run(self.instance)

    def test_plan_instantiation_preserves_mode(self):
        plan=dict(format='gat.document-plan.v1',habitat=str(self.docs),mission='When?',runtime_model='offline',
            abstain=False,rationale='Fixture',designer_usage={},documents=[dict(document_id='a',path='a.md',
            sha256=hashlib.sha256(self.text.encode()).hexdigest())])
        result=instantiate(self.instance,plan,integration=self.integration,isolated=True)
        self.assertEqual(result['format'],gat.ISOLATED_FORMAT)

if __name__=='__main__':unittest.main()
