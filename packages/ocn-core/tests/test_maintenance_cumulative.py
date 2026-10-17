"""Persisted preservation and current-code execution gates, real sandbox."""
import json
import unittest
from unittest.mock import Mock,patch
import test_local_cumulative as fixtures
from ocn_core import gat
from ocn_core.candidate_adoption import adopt
from ocn_core.maintenance_policy import configure,status,tick,read
from ocn_core.maintained_run import run_maintained


class MaintenanceCumulativeTests(unittest.TestCase):
    setUp=fixtures.LocalCumulativeTests.setUp
    bootstrap=fixtures.LocalCumulativeTests.bootstrap

    def configure(self):
        return configure(self.instance,'Keep a normalized and b exact.',self.new,'unavailable-test-model',
                         self.root/'audit',2,preserve_acceptance=True)

    def test_persisted_opt_in_repairs_then_executes_and_keeps_budget(self):
        self.bootstrap('d["text"].lower() if question == "a" else d["text"].strip()')
        configured=self.configure()
        self.assertTrue(configured['preserve_acceptance'])
        self.assertEqual(read(self.instance)['format'],'gat.maintenance.v2')
        first=run_maintained(self.instance,question='b')
        self.assertEqual(first['answer'],' BETA ')
        self.assertEqual(first['maintenance_result']['designer_calls'],0)
        second=run_maintained(self.instance,question='a')
        self.assertEqual(second['answer'],'alpha')
        self.assertEqual(status(self.instance)['used_cycles'],2)
        with self.assertRaisesRegex(RuntimeError,'exhausted'):run_maintained(self.instance)

    def test_rejected_fallback_spends_cycle_without_running_mission(self):
        self.bootstrap('d["text"].lower()');self.configure()
        proposer=Mock(return_value=(fixtures.bridge('d["text"]'),{'model_calls':0}))
        before=(self.instance/'instance.json').read_bytes()
        with patch('ocn_core.maintenance_policy.LocalBridgeRepairer',return_value=proposer),patch('ocn_core.gat.run') as mission:
            with self.assertRaisesRegex(RuntimeError,'did not establish'):
                run_maintained(self.instance,question='b')
            mission.assert_not_called()
        proposer.assert_called_once()
        self.assertEqual(status(self.instance)['used_cycles'],1)
        self.assertEqual((self.instance/'instance.json').read_bytes(),before)

    def test_intervening_adoption_cannot_discard_entry_invariants(self):
        self.bootstrap('d["text"].lower() if question == "a" else d["text"].strip()');self.configure()
        def race(instance):
            result=tick(instance)
            current=json.loads((self.instance/'instance.json').read_text())['integration']['sha256']
            # Ordinary adoption deliberately replaces acceptance with a new case.
            # New code passes b and c but breaks the retained a normalization.
            decision=adopt(instance,fixtures.bridge('d["text"].upper() if question == "c" else d["text"]'),fixtures.suite('c','Gamma','GAMMA'),current)
            self.assertTrue(decision['adopted'])
            return result
        with patch('ocn_core.maintenance_policy.tick',side_effect=race):
            with self.assertRaisesRegex(RuntimeError,'pre-execution acceptance'):
                run_maintained(self.instance,question='b')
        self.assertEqual(status(self.instance)['used_cycles'],1)

    def test_legacy_policy_stays_legacy_and_invalid_new_flag_refuses(self):
        self.bootstrap('d["text"].lower()');self.configure()
        path=self.instance/'maintenance.json';policy=json.loads(path.read_text())
        policy['preserve_acceptance']=1;path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(ValueError,'Boolean acceptance'):read(self.instance)
        policy.pop('preserve_acceptance');policy['format']='gat.maintenance.v1';policy['used_cycles']=1
        path.write_text(json.dumps(policy))
        self.assertFalse(status(self.instance)['preserve_acceptance'])
        self.assertEqual(status(self.instance)['remaining_cycles'],1)
        with patch('ocn_core.maintenance_policy.hybrid_repair',return_value={'status':'already_accepted'}) as repair:
            tick(self.instance)
            self.assertFalse(repair.call_args.kwargs['preserve_acceptance'])
        self.assertEqual(read(self.instance)['format'],'gat.maintenance.v1')
        self.assertEqual(status(self.instance)['remaining_cycles'],0)

if __name__=='__main__':unittest.main()
