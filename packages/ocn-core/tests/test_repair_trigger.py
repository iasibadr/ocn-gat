"""Conditional repair spends no cycle for validated missions; no mission retries."""
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_maintained_run as fixtures
from ocn_core import gat
from ocn_core.maintained_run import run_maintained
from ocn_core.maintenance_policy import status,tick
from ocn_core.candidate_adoption import rollback


class RepairTriggerTests(unittest.TestCase):
    setUp=fixtures.MaintainedRunTests.setUp

    def test_repair_once_then_continue_after_budget_exhaustion_only_if_valid(self):
        first=run_maintained(self.instance,repair_on_failure=True)
        self.assertEqual(first['maintenance_result']['status'],'adopted')
        self.assertEqual(status(self.instance)['used_cycles'],1)
        tick(self.instance)  # Explicit maintenance consumes the last cycle.
        (self.docs/'pad.md').rename(self.docs/'moved.md')
        for _ in range(3):
            result=run_maintained(self.instance,repair_on_failure=True)
            self.assertEqual(result['answer'],self.text)
            self.assertEqual(result['citations'][0]['path'],'moved.md')
            self.assertIsNone(result['maintenance_cycle'])
            self.assertEqual(result['maintenance_result']['status'],'not_needed')
        self.assertEqual(status(self.instance)['used_cycles'],2)
        current=json.loads((self.instance/'instance.json').read_text())['integration']['sha256']
        rollback(self.instance,current)  # Defect returns; no remaining repair authority.
        with self.assertRaisesRegex(RuntimeError,'exhausted'):
            run_maintained(self.instance,repair_on_failure=True)

    def test_inconclusive_sandbox_failure_never_starts_repair(self):
        with patch('ocn_core.candidate_evaluation.run_trial',return_value={'status':'failed'}),patch('ocn_core.maintenance_policy.tick') as repair:
            with self.assertRaisesRegex(RuntimeError,'pre-execution acceptance'):
                run_maintained(self.instance,repair_on_failure=True)
            repair.assert_not_called()
        self.assertEqual(status(self.instance)['used_cycles'],0)

    def test_mission_exception_is_not_retried_or_repaired(self):
        with patch('ocn_core.gat.run',side_effect=RuntimeError('mission failed')) as run,patch('ocn_core.maintenance_policy.tick') as repair:
            with self.assertRaisesRegex(RuntimeError,'mission failed'):
                run_maintained(self.instance,repair_on_failure=True)
            run.assert_called_once();repair.assert_not_called()
        self.assertEqual(status(self.instance)['used_cycles'],0)

    def test_cli_repair_trigger_is_explicit_and_pause_still_blocks(self):
        command=[sys.executable,'-m','ocn_core.gat','run-maintained',str(self.instance),'--repair-on-failure']
        for expected in ('adopted','not_needed','not_needed'):
            done=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(done.returncode,0,done.stderr)
            result=json.loads(done.stdout)
            self.assertEqual(result['answer'],self.text)
            self.assertEqual(result['maintenance_result']['status'],expected)
        self.assertEqual(status(self.instance)['used_cycles'],1)
        gat.set_paused(self.instance,True)
        with self.assertRaisesRegex(RuntimeError,'paused'):
            run_maintained(self.instance,repair_on_failure=True)
        self.assertEqual(status(self.instance)['used_cycles'],1)

if __name__=='__main__':unittest.main()
