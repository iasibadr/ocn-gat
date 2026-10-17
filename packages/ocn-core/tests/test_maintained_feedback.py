"""Connect maintained missions to receipts without recording failed preflights."""
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_maintained_run as fixtures
from ocn_core import gat
from ocn_core.maintained_run import run_maintained
from ocn_core.maintenance_policy import authority,status
from ocn_core.memory_maintenance import before_run_locked
from ocn_core.run_feedback import action_id,feedback,RecordedRunError


class MaintainedFeedbackTests(unittest.TestCase):
    setUp=fixtures.MaintainedRunTests.setUp

    def test_failed_gate_does_not_prepare_receipt_or_maintain_memory(self):
        _,config=gat.load(self.instance)
        with patch('ocn_core.memory_maintenance.before_run_locked') as maintenance:
            with self.assertRaisesRegex(RuntimeError,'pre-execution acceptance'):
                gat.run(self.instance,record=True,acceptance_suite=self.suite,expected_authority=authority(config))
            maintenance.assert_not_called()
        self.assertFalse((self.instance/'run-receipts').exists())
        self.assertFalse((self.instance/'feedback-memory').exists())
        self.assertEqual(status(self.instance)['used_cycles'],0)

    def test_repair_then_record_prepares_once_for_the_executed_revision(self):
        _,before=gat.load(self.instance)
        with patch('ocn_core.memory_maintenance.before_run_locked',wraps=before_run_locked) as maintenance:
            result=run_maintained(self.instance,repair_on_failure=True,record=True)
            maintenance.assert_called_once()
        _,after=gat.load(self.instance);receipt=result['run_receipt']
        self.assertEqual(receipt['action'],action_id(after,after['model']))
        self.assertNotEqual(receipt['action'],action_id(before,before['model']))
        self.assertEqual(receipt['status'],'completed')
        self.assertEqual(len(list((self.instance/'run-receipts').glob('*.json'))),1)
        self.assertFalse((self.instance/'feedback-memory').exists())
        result=feedback(self.instance,receipt['run_id'],rubric='exact-text-v1',success=True,quality=1,interventions=0)
        self.assertTrue(result['recorded']);self.assertEqual(result['estimate']['observations'],1)
        self.assertFalse(feedback(self.instance,receipt['run_id'],rubric='exact-text-v1',success=True,quality=1,interventions=0)['recorded'])

    def test_mission_failure_recorded_once_without_repair_retry(self):
        run_maintained(self.instance,repair_on_failure=True)
        (self.docs/'pad.md').unlink()
        with self.assertRaises(RecordedRunError) as failure:
            run_maintained(self.instance,repair_on_failure=True,record=True)
        receipt=failure.exception.receipt
        self.assertEqual(receipt['status'],'failed')
        self.assertEqual(status(self.instance)['used_cycles'],1)
        self.assertEqual(len(list((self.instance/'run-receipts').glob('*.json'))),1)
        self.assertFalse((self.instance/'feedback-memory').exists())
        with self.assertRaisesRegex(ValueError,'Failed run feedback'):
            feedback(self.instance,receipt['run_id'],rubric='exact-text-v1',success=True,quality=1,interventions=0)
        self.assertTrue(feedback(self.instance,receipt['run_id'],rubric='exact-text-v1',success=False,quality=0,interventions=1)['recorded'])

    def test_version_scope_survives_repair_and_healthy_maintained_execution(self):
        first=run_maintained(self.instance,repair_on_failure=True,record=True,feedback_scope='document_versions')
        second=run_maintained(self.instance,repair_on_failure=True,record=True,feedback_scope='document_versions')
        self.assertEqual(first['run_receipt']['feedback_scope'],'document_versions')
        self.assertEqual(first['run_receipt']['context'],second['run_receipt']['context'])
        self.assertEqual(second['maintenance_result']['status'],'not_needed')
        self.assertEqual(status(self.instance)['used_cycles'],1)

    def test_cli_records_healthy_conditional_mission_and_pause_blocks(self):
        run_maintained(self.instance,repair_on_failure=True)
        command=[sys.executable,'-m','ocn_core.gat','run-maintained',str(self.instance),'--repair-on-failure','--record']
        done=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr)
        result=json.loads(done.stdout)
        self.assertEqual(result['answer'],self.text)
        self.assertEqual(result['maintenance_result']['status'],'not_needed')
        self.assertEqual(result['run_receipt']['status'],'completed')
        self.assertEqual(status(self.instance)['used_cycles'],1)
        gat.set_paused(self.instance,True)
        refused=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertNotEqual(refused.returncode,0)
        self.assertEqual(len(list((self.instance/'run-receipts').glob('*.json'))),1)

if __name__=='__main__':unittest.main()
