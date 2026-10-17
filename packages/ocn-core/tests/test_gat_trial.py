import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import prepare


class GATTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.text='Delivery Friday.';(self.docs/'a.md').write_text(self.text)
        self.source=self.root/'candidate.py'
        self.source.write_text('raise RuntimeError("Must never execute on host")\ndef build_synthesizer(model): return None\n')
        self.instance=self.root/'instance'
        gat.create(self.instance,self.docs,{'a':'a.md'},'When?',integration=prepare(self.source))
        self.original=(self.instance/'agent.py').read_bytes()

    def response(self,quote=None):
        return dict(status='completed',source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            result=dict(response=dict(answer=self.text,abstain=False,
                citations=[dict(document_id='a',quote=self.text if quote is None else quote)]),
                usage=dict(model_calls=999,execution='host')))

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_relocation_and_usage_without_promotion(self, run):
        run.return_value=self.response();(self.docs/'a.md').rename(self.docs/'b.md')
        result=gat.trial(self.instance,self.source)
        self.assertEqual(result['citations'][0]['path'],'b.md')
        self.assertEqual(result['usage']['execution'],'offline_bubblewrap')
        self.assertEqual(result['usage']['host_model_calls'],0)
        self.assertEqual(result['usage']['candidate_reported']['model_calls'],999)
        self.assertEqual((self.instance/'agent.py').read_bytes(),self.original)
        self.assertEqual(run.call_args.kwargs['documents'][0]['text'],self.text)

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_unsupported_quote_rejected(self, run):
        run.return_value=self.response('invented')
        with self.assertRaisesRegex(ValueError,'Citation'):gat.trial(self.instance,self.source)

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_change_during_trial_rejected(self, run):
        def change(*args,**kwargs):
            (self.docs/'a.md').write_text('Changed version.')
            return self.response()
        run.side_effect=change
        with self.assertRaises(ValueError):gat.trial(self.instance,self.source)

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_paused_and_oversize_do_not_start_candidate(self, run):
        gat.set_paused(self.instance,True)
        with self.assertRaises(RuntimeError):gat.trial(self.instance,self.source)
        run.assert_not_called()
        gat.set_paused(self.instance,False)
        with self.assertRaises(ValueError):gat.trial(self.instance,self.source,question='x'*4097)
        run.assert_not_called()

    @patch('ocn_core.sandbox_trial.run_trial')
    def test_failed_sandbox_never_falls_back(self, run):
        run.return_value=dict(status='failed',reason='wall_timeout')
        with self.assertRaisesRegex(RuntimeError,'wall_timeout'):gat.trial(self.instance,self.source)
        run.side_effect=RuntimeError('Bubblewrap required')
        with self.assertRaisesRegex(RuntimeError,'Bubblewrap'):gat.trial(self.instance,self.source)
        self.assertEqual((self.instance/'agent.py').read_bytes(),self.original)

if __name__=='__main__':unittest.main()
