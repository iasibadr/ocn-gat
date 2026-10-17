import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.hybrid_repair import hybrid_repair


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);docs=self.root/'docs';docs.mkdir();(docs/'a.md').write_text('Friday')
        self.instance=self.root/'instance';self.output=self.root/'audit';self.proposer=Mock()
        gat.create(self.instance,docs,{'a':'a.md'},'When?',integration=Integration(b'def build_synthesizer(model): return None','build_synthesizer'),isolated=True)
        self.suite={'format':'gat.acceptance-suite.v1','cases':[dict(id='one',question='When?',documents=[dict(document_id='a',text='Friday')],
            expected={'response':dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')])})]}

    @patch('ocn_core.hybrid_repair.repair')
    @patch('ocn_core.hybrid_repair.local_repair')
    def test_local_success_or_non_miss_never_calls_designer(self,local,repair):
        for index,status in enumerate(('adopted','already_accepted','not_adopted')):
            local.return_value={'status':status}
            result=hybrid_repair(self.instance,'Contract',self.suite,self.proposer,self.root/str(index))
            self.assertEqual(result['designer_calls'],0)
        repair.assert_not_called();self.proposer.assert_not_called()

    @patch('ocn_core.hybrid_repair.repair')
    @patch('ocn_core.hybrid_repair.local_repair')
    def test_only_conclusive_miss_enables_one_designer_phase(self,local,repair):
        local.return_value={'status':'no_passing_candidate'}
        repair.return_value={'status':'adopted','designer_calls':1}
        result=hybrid_repair(self.instance,'Contract',self.suite,self.proposer,self.output,share_acceptance_feedback=True)
        self.assertEqual(result['route'],'local_then_designer')
        repair.assert_called_once()
        self.assertTrue(repair.call_args.kwargs['share_acceptance_feedback'])

    @patch('ocn_core.hybrid_repair.repair')
    @patch('ocn_core.hybrid_repair.local_repair',side_effect=OSError('uncertain disk result'))
    def test_failure_never_falls_back(self,local,repair):
        with self.assertRaises(OSError):hybrid_repair(self.instance,'Contract',self.suite,self.proposer,self.output)
        repair.assert_not_called()
        self.assertFalse(json.loads((self.output/'failure.json').read_text())['automatic_retry'])

    @patch('ocn_core.hybrid_repair.local_repair')
    def test_existing_audit_and_invalid_options_fail_before_work(self,local):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):hybrid_repair(self.instance,'Contract',self.suite,self.proposer,self.output)
        with self.assertRaises(ValueError):hybrid_repair(self.instance,'Contract',self.suite,self.proposer,self.root/'new',limit=True)
        local.assert_not_called()

if __name__=='__main__':unittest.main()
