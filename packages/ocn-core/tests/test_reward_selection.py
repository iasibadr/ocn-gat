import unittest
import numpy as np
from ocn_core.viability import transition_envelope
from ocn_core.reward_selection import ActionForecast,select_action,discounted_return


class RewardSelectionTests(unittest.TestCase):
    def setUp(self):
        self.safe=transition_envelope(np.eye(4),[.5]*4,[.1]*4)
        self.options=dict(authorized={'quick','thorough'},minimum=[0]*4,maximum=[1]*4,reserve=10,reserve_floor=2)

    def test_higher_reward_wins_despite_worse_reward_per_cost(self):
        candidates=[ActionForecast('quick',self.safe,5,1),ActionForecast('thorough',self.safe,9,7)]
        result=select_action(candidates,**self.options)
        self.assertEqual(result['action_id'],'thorough')
        self.assertEqual(result['expected_return'],9)

    def test_reserve_is_a_constraint_not_a_reward_penalty(self):
        candidates=[ActionForecast('quick',self.safe,5,1),ActionForecast('thorough',self.safe,9,9)]
        result=select_action(candidates,**self.options)
        self.assertEqual(result['action_id'],'quick')
        self.assertEqual(result['assessments'][1]['reason'],'not_viable')

    def test_permission_cannot_be_bought_by_reward(self):
        result=select_action([ActionForecast('unapproved',self.safe,1e9,0)],**self.options)
        self.assertTrue(result['abstained'])
        self.assertEqual(result['assessments'][0]['reason'],'not_authorized')

    def test_state_uncertainty_can_force_abstention(self):
        unsafe=transition_envelope(np.eye(4),[.5]*4,[.6]*4)
        result=select_action([ActionForecast('thorough',unsafe,100,1)],**self.options)
        self.assertTrue(result['abstained'])

    def test_future_reward_can_justify_immediate_investment(self):
        immediate=discounted_return([3,0,0],.9)
        learning=discounted_return([-1,3,4],.9)
        result=select_action([ActionForecast('quick',self.safe,immediate,1),
                             ActionForecast('thorough',self.safe,learning,7)],**self.options)
        self.assertEqual(result['action_id'],'thorough')

    def test_bad_forecasts_fail_and_negative_return_can_abstain(self):
        result=select_action([ActionForecast('quick',self.safe,-1,1)],**self.options)
        self.assertTrue(result['abstained'])
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):select_action([ActionForecast('quick',self.safe,value,1)],**self.options)
        with self.assertRaises(ValueError):discounted_return([1],1.1)
        with self.assertRaises(ValueError):discounted_return([1e308,1e308],1.)
        with self.assertRaises(ValueError):select_action([ActionForecast('quick',self.safe,1,1)]*2,**self.options)


if __name__=='__main__':unittest.main()
