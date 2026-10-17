import unittest
from copy import deepcopy
from ocn_core.managed_skill_session import ManagedSkillSession


def session():
    return ManagedSkillSession(lambda c,r,s,i,e:dict(value=s['city']),
        lambda c,r,s,i,o:o['value']==s['city'],learn_from_feedback=True,
        skill_kind='text',max_requests=64,max_worker_calls=64)


def call(s,key,n):
    return s.run(key,'fixed',dict(id=f'item-{key}-{n}',city=f'City-{n}'),f'item-{key}-{n}',
        allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)


class ManagedMemoryTests(unittest.TestCase):
    def test_complete_retirement_and_relearning_without_new_permission(self):
        s=session();s.permit('a','fixed')
        for n in range(3):call(s,'a',n)
        before=deepcopy(s.permissions);calls=s.worker_calls
        result=s.trim_memory(0)
        self.assertEqual(result['retired'],['a'])
        self.assertFalse(result['target_met']) # Immutable authority/audit still costs bytes.
        self.assertGreater(result['bytes_released'],0)
        self.assertEqual(s.permissions,before)
        self.assertNotIn('a',s.bank.authority)
        self.assertNotIn('a',s.bank.entries)
        self.assertNotIn('a',s.examples)
        self.assertNotIn('a',s.learned_calibrations)
        self.assertEqual([call(s,'a',n)['action'] for n in range(3,6)],
                         ['delegate','delegate','acquire_apply'])
        self.assertEqual(s.worker_calls-calls,2)

    def test_host_calibration_and_protected_learning_survive(self):
        s=session();s.permit('a','fixed')
        for n in range(3):call(s,'a',n)
        examples=[dict(record=dict(id=str(n),city=f'Town-{n}'),identity=str(n),expected=f'Town-{n}') for n in range(2)]
        s.authorize('host','fixed',examples)
        authority=deepcopy(s.bank.authority)
        r=s.trim_memory(0,protect=['a'])
        self.assertEqual(r['retired'],[]);self.assertFalse(r['target_met'])
        self.assertEqual(s.bank.authority,authority)

    def test_pending_examples_removed_and_target_already_met_is_noop(self):
        s=session();s.permit('a','fixed');call(s,'a',0)
        before=deepcopy(s._state())
        r=s.trim_memory(s.memory_report()['serialized_bytes'])
        self.assertTrue(r['target_met']);self.assertEqual(before,s._state())
        self.assertEqual(s.trim_memory(0)['retired'],['a'])
        self.assertEqual(s.examples,{})

    def test_recency_preserves_recent_scope(self):
        s=session()
        for k in ('a','b'):
            s.permit(k,'fixed')
            for n in range(3):call(s,k,n)
        call(s,'a',4)
        r=s.trim_memory(0)
        self.assertEqual(r['retired'],['b','a'])

    def test_invalid_target_and_reentrant_maintenance_do_not_mutate(self):
        s=session();s.permit('a','fixed');before=deepcopy(s._state())
        for value in (-1,True,1.2,'1'):
            with self.assertRaises(ValueError):s.trim_memory(value)
        with self.assertRaises(ValueError):s.trim_memory(0,protect=['unknown'])
        self.assertEqual(before,s._state())
        s.worker=lambda *args:s.trim_memory(0)
        with self.assertRaisesRegex(RuntimeError,'busy'):call(s,'a',0)
        self.assertEqual(s.worker_calls,1)
        self.assertEqual(s.examples,{})


if __name__=='__main__':unittest.main()
