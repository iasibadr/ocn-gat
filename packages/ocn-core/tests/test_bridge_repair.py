import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core import gat
from ocn_core.agent_integration import prepare
from ocn_core.bridge_repair import repair


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        (self.docs/'a.md').write_text('Friday')
        self.code=self.root/'code.py';self.code.write_text('def build_synthesizer(model): return None\n')
        self.integration=prepare(self.code);self.instance=self.root/'instance';self.output=self.root/'audit'
        gat.create(self.instance,self.docs,{'a':'a.md'},'When?',integration=self.integration,isolated=True)
        self.suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='one',question='When?',
            documents=[dict(document_id='a',text='Friday')],expected={'response':dict(answer='Friday',abstain=False,
            citations=[dict(document_id='a',quote='Friday')])})])

    @patch('ocn_core.bridge_repair.adopt')
    @patch('ocn_core.bridge_repair.evaluate')
    def test_single_proposal_without_test_oracle(self,evaluate,adopt):
        evaluate.return_value=dict(accepted=False,suite_sha256='a'*64)
        adopt.return_value=dict(adopted=True)
        def propose(source,contract,entrypoint):
            self.assertTrue((self.output/'attempt.json').exists())
            self.assertEqual((source,contract,entrypoint),(self.integration.source.decode(),'Contract','build_synthesizer'))
            return self.integration,{'model_calls':1}
        proposer=Mock(side_effect=propose)
        result=repair(self.instance,'Contract',self.suite,proposer,self.output)
        self.assertEqual(result['status'],'adopted');proposer.assert_called_once()
        self.assertEqual(adopt.call_args.args[3],self.integration.descriptor()['sha256'])

    @patch('ocn_core.bridge_repair.evaluate')
    def test_passing_baseline_skips_designer(self,evaluate):
        evaluate.return_value=dict(accepted=True)
        proposer=Mock()
        result=repair(self.instance,'Contract',self.suite,proposer,self.output)
        self.assertEqual(result['designer_calls'],0);proposer.assert_not_called()

    @patch('ocn_core.bridge_repair.adopt')
    @patch('ocn_core.bridge_repair.evaluate')
    def test_failure_recorded_without_retry_or_adoption(self,evaluate,adopt):
        evaluate.return_value=dict(accepted=False,suite_sha256='a'*64)
        proposer=Mock(side_effect=TimeoutError('secret error details'))
        with self.assertRaises(TimeoutError):repair(self.instance,'Contract',self.suite,proposer,self.output)
        proposer.assert_called_once();adopt.assert_not_called()
        failure=(self.output/'failure.json').read_text()
        self.assertNotIn('secret',failure);self.assertTrue(json.loads(failure)['inspect_instance_before_retry'])

    @patch('ocn_core.bridge_repair.evaluate')
    def test_existing_output_refuses_designer(self,evaluate):
        evaluate.return_value=dict(accepted=False,suite_sha256='a'*64)
        self.output.mkdir();proposer=Mock()
        with self.assertRaises(FileExistsError):repair(self.instance,'Contract',self.suite,proposer,self.output)
        proposer.assert_not_called()

if __name__=='__main__':unittest.main()
