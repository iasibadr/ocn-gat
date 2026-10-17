from dataclasses import replace
import unittest
import numpy as np
from ocn_core.possibility_space import ActionModel, explore


class PossibilitySpaceTests(unittest.TestCase):
    def plan(self,actions,**kw):
        args=dict(initial=(1.,0.,0.,0.),anchor_id='host-observation-1',coordinate_contract='fixture-v1',
            authorized={a.action_id for a in actions},minimum=(-2,)*4,maximum=(2,)*4,reserve=10.)
        args.update(kw);return explore(actions=actions,**args)

    def test_order_changes_hypotheses_without_creating_observations(self):
        actions=[ActionModel('i',(0,)*4,0.,.1,left=(0,1,0,0)),
                 ActionModel('j',(0,)*4,0.,.1,left=(0,0,1,0)),
                 ActionModel('finish',(0,)*4,1.,.1,terminal=True)]
        result=self.plan(actions)
        rows={tuple(r['path']):r for r in result['explored']}
        np.testing.assert_allclose(rows['i','j']['state'],[0,0,0,-1],atol=1e-15)
        np.testing.assert_allclose(rows['j','i']['state'],[0,0,0,1],atol=1e-15)
        self.assertFalse(result['facts_created']);self.assertEqual(result['actions_executed'],0)
        self.assertEqual(result['proposal']['status'],'predicted')

    def test_budget_exhaustion_does_not_promote_provisional_best(self):
        a=ActionModel('first',(0,)*4,2.,0.,terminal=True)
        b=replace(a,action_id='unexplored',predicted_reward=4.)
        result=self.plan([a,b],max_expansions=1)
        self.assertEqual(result['status'],'incomplete')
        self.assertIsNone(result['action_id']);self.assertIsNone(result['proposal'])
        self.assertEqual(result['expansions'],1)
        unfinished=self.plan([replace(a,terminal=False)],horizon=1)
        self.assertEqual(unfinished['status'],'abstained')

    def test_reward_priority_permissions_and_reserve(self):
        a=ActionModel('cheap',(0,)*4,1.,1.,terminal=True)
        b=replace(a,action_id='useful',predicted_reward=3.,cost_upper=2.)
        denied=replace(a,action_id='forbidden',predicted_reward=100.)
        result=self.plan([a,b,denied],authorized={'cheap','useful'},reserve=3.,reserve_floor=1.)
        self.assertEqual(result['action_id'],'useful')
        self.assertEqual(result['explored'][-1]['reason'],'not_authorized')
        result=self.plan([a,b],reserve=2.,reserve_floor=1.)
        self.assertEqual(result['action_id'],'cheap')
        equal=self.plan([replace(b,predicted_reward=1.),a])
        self.assertEqual(equal['action_id'],'cheap')

    def test_membrane_passes_only_selected_complex_plane(self):
        a=ActionModel('exchange',(0.,1.,2.,3.),1.,0.,terminal=True,parallel_gate=1.)
        result=self.plan([a],initial=(4,5,6,7),minimum=(-10,)*4,maximum=(10,)*4)
        self.assertEqual(result['proposal']['state'],[0.,1.,6.,7.])

    def test_declared_error_accumulates_and_invalid_model_is_refused(self):
        a=ActionModel('prepare',(0,)*4,0.,0.,error_bound=(.4,)*4)
        b=replace(a,action_id='finish',predicted_reward=1.,terminal=True)
        result=self.plan([a,b],initial=(0,)*4,minimum=(-.5,)*4,maximum=(.5,)*4)
        rows={tuple(r['path']):r for r in result['explored']}
        self.assertEqual(rows['prepare','finish']['reason'],'predicted_viability_constraint')
        self.assertEqual(result['proposal']['path'],['finish'])
        for invalid in (replace(a,left=(2,0,0,0)),replace(a,plane=(1,0,0,0)),
                        replace(a,cost_upper=-1.),replace(a,predicted_reward=float('nan'))):
            with self.assertRaises(ValueError):self.plan([invalid])

    def test_document_prerequisites_require_ordered_plan(self):
        locate=ActionModel('locate',(0,)*4,0.,1.,adds=('located',))
        read=ActionModel('read',(0,)*4,0.,1.,requires=('located',),adds=('read',))
        summarize=ActionModel('summarize',(0,)*4,5.,1.,terminal=True,requires=('read',))
        result=self.plan([summarize,read,locate],horizon=3)
        self.assertEqual(result['proposal']['path'],['locate','read','summarize'])
        self.assertEqual(result['action_id'],'locate')
        self.assertEqual(result['initial_conditions'],[])
        self.assertFalse(result['facts_created'])
        rows={tuple(r['path']):r for r in result['explored']}
        self.assertEqual(rows['summarize',]['reason'],'missing_predicted_preconditions')
        # A sibling's predicted read must never leak back into the root state.
        self.assertEqual(rows['read',]['missing'],['located'])

    def test_invalidated_condition_and_replanning(self):
        invalidate=ActionModel('invalidate',(0,)*4,0.,0.,removes=('read',))
        finish=ActionModel('finish',(0,)*4,1.,0.,terminal=True,requires=('read',))
        result=self.plan([invalidate,finish],initial_conditions=('read',),horizon=2)
        rows={tuple(r['path']):r for r in result['explored']}
        self.assertEqual(rows['invalidate','finish']['reason'],'missing_predicted_preconditions')
        self.assertEqual(result['proposal']['path'],['finish'])
        self.assertEqual(result['initial_condition_status'],'host_declared')
        with self.assertRaises(ValueError):self.plan([replace(finish,adds=('read',),removes=('read',))])

    def test_temperature_concentrates_preference_not_execution(self):
        a=ActionModel('useful',(0,)*4,4.,5.,terminal=True)
        b=replace(a,action_id='cheap',predicted_reward=1.,cost_upper=0.)
        cold=self.plan([a,b],decision_temperature=.1)
        warm=self.plan([a,b],decision_temperature=10.)
        self.assertLess(cold['decision_entropy_nats'],warm['decision_entropy_nats'])
        probs={r['action_id']:r['probability'] for r in cold['decision_distribution']}
        self.assertGreater(probs['useful'],.99)
        self.assertAlmostEqual(sum(probs.values()),1.)
        self.assertIsNone(cold['action_id']);self.assertIsNone(cold['proposal'])
        self.assertEqual(cold['actions_executed'],0)

    def test_distribution_excludes_forbidden_and_incomplete(self):
        a=ActionModel('a',(0,)*4,4.,0.,terminal=True)
        b=replace(a,action_id='b')
        result=self.plan([a,b],authorized={'a'},decision_temperature=1.)
        self.assertEqual([r['action_id'] for r in result['decision_distribution']],[None,'a'])
        cut=self.plan([a,b],max_expansions=1,decision_temperature=1.)
        self.assertIsNone(cut['decision_distribution'])
        self.assertEqual(cut['status'],'incomplete')

    def test_abstention_and_extreme_utilities(self):
        a=ActionModel('bad',(0,)*4,-1e308,0.,terminal=True)
        result=self.plan([a],decision_temperature=1e-300)
        self.assertEqual(result['decision_distribution'][0]['probability'],1.)
        self.assertEqual(result['decision_entropy_nats'],0.)
        for t in (0.,-1.,float('nan'),True):
            with self.assertRaises(ValueError):self.plan([a],decision_temperature=t)

    def test_duplicate_continuations_do_not_increase_action_mass(self):
        start=ActionModel('start',(0,)*4,0.,0.,adds=('ready',))
        end=ActionModel('end',(0,)*4,2.,0.,terminal=True,requires=('ready',))
        extra=replace(end,action_id='extra')
        one=self.plan([start,end],horizon=2,decision_temperature=1.)
        two=self.plan([start,end,extra],horizon=2,decision_temperature=1.)
        self.assertEqual(one['decision_distribution'],two['decision_distribution'])


if __name__=='__main__':unittest.main()
