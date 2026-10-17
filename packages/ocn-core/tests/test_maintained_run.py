import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.maintenance_policy import configure,status
from ocn_core.maintained_run import run_maintained

PACKAGE=Path(__file__).resolve().parents[1]

class MaintainedRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.docs=root/'docs';self.docs.mkdir()
        self.text='  Keep these spaces.  ';(self.docs/'pad.md').write_text(self.text)
        self.instance=root/'instance'
        code=(PACKAGE/'benchmarks/bridge_repair_v7/trim.py').read_bytes()
        gat.create(self.instance,self.docs,{'pad':'pad.md'},'pad',model='offline',
            integration=Integration(code,'build_synthesizer'),isolated=True)
        self.suite=json.loads((PACKAGE/'benchmarks/bridge_repair_v7/acceptance.json').read_text())
        configure(self.instance,'Return exactly the requested text.',self.suite,
            'intentionally-unavailable',root/'audit',2)

    def test_repair_then_answer_relocation_and_finite_budget(self):
        first=run_maintained(self.instance)
        self.assertEqual(first['answer'],self.text)
        self.assertEqual(first['maintenance_result']['status'],'adopted')
        self.assertEqual(first['maintenance_result']['designer_calls'],0)
        (self.docs/'pad.md').rename(self.docs/'moved.md')
        second=run_maintained(self.instance)
        self.assertEqual(second['answer'],self.text)
        self.assertEqual(second['citations'][0]['path'],'moved.md')
        self.assertEqual(second['maintenance_result']['status'],'already_accepted')
        with self.assertRaisesRegex(RuntimeError,'exhausted'):run_maintained(self.instance)
        self.assertEqual(status(self.instance)['used_cycles'],2)

    def test_pause_does_not_consume_cycle(self):
        gat.set_paused(self.instance,True)
        with self.assertRaisesRegex(RuntimeError,'paused'):run_maintained(self.instance)
        self.assertEqual(status(self.instance)['used_cycles'],0)

    def test_rejected_repair_never_runs_mission(self):
        with patch('ocn_core.maintenance_policy.tick',return_value={'cycle':1,'result':{'status':'rejected'}}),patch('ocn_core.gat.run') as run:
            with self.assertRaisesRegex(RuntimeError,'did not establish'):run_maintained(self.instance)
            run.assert_not_called()

    def test_historical_acceptance_cannot_bypass_current_code_check(self):
        with patch('ocn_core.maintenance_policy.tick',return_value={'cycle':1,'result':{'status':'already_accepted'}}):
            # Actual current bridge still strips spaces and fails the suite.
            with self.assertRaisesRegex(RuntimeError,'pre-execution acceptance'):run_maintained(self.instance)
        with self.assertRaisesRegex(ValueError,'authority snapshot'):
            gat.run(self.instance,acceptance_suite=self.suite)
        with self.assertRaisesRegex(ValueError,'authority changed'):
            gat.run(self.instance,acceptance_suite=self.suite,expected_authority='wrong')

if __name__=='__main__':unittest.main()
