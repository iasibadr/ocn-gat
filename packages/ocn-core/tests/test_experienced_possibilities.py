from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.possibility_space import ActionModel
from ocn_core.experienced_possibilities import explore_from_experience


class ExperiencedPossibilitiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.memory=ExperienceMemory.create(Path(self.tmp.name)/'memory.sqlite',
            contract_id='fixture-v1',actions=['quick','deep'])
        self.models=[ActionModel('quick',(0,)*4,999.,0.,terminal=True),
                     ActionModel('deep',(0,)*4,-999.,5.,terminal=True)]
        self.serial=0

    def record(self,action,success,quality=0.,interventions=0):
        self.serial+=1
        self.memory.record(event_id=str(self.serial),context='documents',action=action,
            success=success,quality=quality,interventions=interventions,cost=None)

    def decide(self,context='documents',**overrides):
        args=dict(authorized={'quick','deep'},decision_temperature=.1,
            anchor_id='observation',coordinate_contract='fixture-v1',
            minimum=(-2,)*4,maximum=(2,)*4,reserve=10.)
        args.update(overrides)
        return explore_from_experience(self.memory,context,(1,0,0,0),self.models,**args)

    def test_outcomes_reverse_preferences_without_manual_reward_leakage(self):
        for _ in range(3):self.record('quick',True);self.record('deep',False)
        first=self.decide()
        self.assertEqual(max(first['decision_distribution'],key=lambda r:r['probability'])['action_id'],'quick')
        for _ in range(8):self.record('quick',False);self.record('deep',True)
        path=self.memory.path;before=path.read_bytes()
        later=self.decide()
        self.assertEqual(max(later['decision_distribution'],key=lambda r:r['probability'])['action_id'],'deep')
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(later['feedback_written']);self.assertEqual(later['actions_executed'],0)
        self.assertTrue(all(0<=e['expected_return']<=1 for e in later['reward_estimates']))

    def test_unobserved_context_and_insufficient_history_abstain(self):
        self.record('quick',True)
        for context in ('documents','new-context'):
            result=self.decide(context)
            self.assertEqual(result['status'],'abstained')
            self.assertEqual(result['decision_distribution'],[
                dict(action_id=None,predicted_value=0.,probability=1.)])
        for invalid in (dict(horizon=2),dict(decision_temperature=None),dict(authorized={1}),
                        dict(success_weight=0.,quality_weight=0.)):
            with self.assertRaises(ValueError):self.decide(**invalid)
        self.models[0]=replace(self.models[0],terminal=False)
        with self.assertRaises(ValueError):self.decide()

    def test_reward_revaluation_and_permissions_remain_separate(self):
        for _ in range(3):
            self.record('quick',True,quality=.1,interventions=1)
            self.record('deep',True,quality=.9)
        result=self.decide(success_weight=0.,quality_weight=1.,intervention_penalty=.5)
        self.assertEqual(max(result['decision_distribution'],key=lambda r:r['probability'])['action_id'],'deep')
        denied=self.decide(authorized={'quick'})
        self.assertNotIn('deep',[r['action_id'] for r in denied['decision_distribution']])
        constrained=self.decide(reserve=0.)
        self.assertNotIn('deep',[r['action_id'] for r in constrained['decision_distribution']])


if __name__=='__main__':unittest.main()
