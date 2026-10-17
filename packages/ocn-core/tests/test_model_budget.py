import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import prepare


class PersistentBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        (self.docs/'a.md').write_text('Friday')
        self.source=self.root/'candidate.py';self.source.write_text('def build_synthesizer(model): return None\n')
        self.instance=self.root/'instance';self.integration=prepare(self.source)
        gat.create(self.instance,self.docs,{'a':'a.md'},'When?',integration=self.integration,isolated=True,model_calls=1)
        self.request=dict(status='completed',source_sha256=self.integration.descriptor()['sha256'],
            result={'request':{'operation':'synthesize','document_ids':['a']}})
        self.answer=dict(response=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')]),usage={})

    @patch('ocn_core.model_broker.LocalDocumentSynthesizer.__call__')
    @patch('ocn_core.model_broker.run_trial')
    def test_reservation_precedes_model_and_survives_reopen(self,trial,model):
        trial.return_value=self.request
        def invoke(*args):
            self.assertEqual(json.loads((self.instance/'model-budget.json').read_text())['used'],1)
            return self.answer
        model.side_effect=invoke
        result=gat.run(self.instance)
        self.assertEqual(result['usage']['budget_reservation'],{'limit':1,'used':1})
        self.assertEqual(gat.status(str(self.instance))['model_budget']['used'],1)
        with self.assertRaisesRegex(RuntimeError,'exhausted'):gat.run(str(self.instance))
        with self.assertRaisesRegex(RuntimeError,'exhausted'):gat.trial(self.instance,self.source,allow_model=True)
        self.assertEqual(model.call_count,1);self.assertEqual(trial.call_count,1)

    @patch('ocn_core.model_broker.LocalDocumentSynthesizer.__call__')
    @patch('ocn_core.model_broker.run_trial')
    def test_timeout_consumes_attempt(self,trial,model):
        trial.return_value=self.request;model.side_effect=TimeoutError('uncertain server completion')
        with self.assertRaises(TimeoutError):gat.run(self.instance)
        with self.assertRaisesRegex(RuntimeError,'exhausted'):gat.run(self.instance)
        self.assertEqual(model.call_count,1)

    @patch('ocn_core.model_broker.LocalDocumentSynthesizer.__call__')
    @patch('ocn_core.model_broker.run_trial')
    def test_bad_candidate_does_not_spend(self,trial,model):
        trial.return_value=dict(status='completed',result={'request':{'operation':'shell'}},source_sha256='x')
        with self.assertRaises(ValueError):gat.run(self.instance)
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],0)
        model.assert_not_called()

    @patch('ocn_core.model_broker.LocalDocumentSynthesizer.__call__')
    def test_corrupt_missing_budget_and_model_override_fail_closed(self,model):
        with self.assertRaisesRegex(ValueError,'overridden'):gat.run(self.instance,model='other')
        path=self.instance/'model-budget.json'
        path.write_text('{"limit":1,"used":false}')
        with self.assertRaises(ValueError):gat.run(self.instance)
        path.unlink()
        with self.assertRaises(OSError):gat.run(self.instance)
        model.assert_not_called()

    @patch('ocn_core.model_broker.LocalDocumentSynthesizer.__call__')
    @patch('ocn_core.model_broker.run_trial')
    def test_failed_reservation_never_calls_model(self,trial,model):
        trial.return_value=self.request
        with patch('ocn_core.model_budget.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):gat.run(self.instance)
        model.assert_not_called()
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],0)

if __name__=='__main__':unittest.main()
