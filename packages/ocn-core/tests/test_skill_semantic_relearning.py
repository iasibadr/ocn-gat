import unittest
from copy import deepcopy
from ocn_core.skill_session import SkillSession


class SemanticRelearningTests(unittest.TestCase):
    def session(self):
        return SkillSession(lambda c,r,s,i,e:{'value':s[s['selected']]},
            lambda c,r,s,i,o:o['value']==s[s['selected']],learn_from_feedback=True,
            adapt_schema_changes=True,identity_guard=lambda c,r,s,i:s.get('id')==i)

    def task(self,s,n,selected='mass'):
        return s.run('A','1',{'id':str(n),'mass':f'{n*10} g','net':f'{n*100} g',
                            'selected':selected},str(n),allowance=12,
                     acquisition_cost=3,application_cost=1,delegation_cost=8)

    def test_rejected_learned_method_retires_and_relearns(self):
        s=self.session();s.permit('A','1')
        for n in range(1,4): self.task(s,n)
        self.assertIn('A',s.learned_calibrations)
        with self.assertRaisesRegex(ValueError,'semantic'): self.task(s,4,'net')
        self.assertNotIn('A',s.bank.authority)
        self.assertNotIn('A',s.examples)
        self.assertEqual(s.permissions,{'A':'1'})
        rows=[self.task(s,n,'net') for n in range(5,8)]
        self.assertEqual([r['action'] for r in rows],['delegate','delegate','acquire_apply'])
        self.assertEqual(s.worker_calls,4)
        self.assertEqual(s.schema_events,[])  # Exactly the same structure throughout.
        self.assertEqual(len(s.retirement_events),1)
        self.assertEqual(s.retirement_events[0]['reason'],'host_semantic_verdict')

    def test_manual_calibration_never_replaced_by_semantic_feedback(self):
        s=self.session();s.permit('A','1')
        for n in range(1,4):self.task(s,n)
        explicit=deepcopy(s.bank.authority['A']['examples'])
        s.authorize('A','1',explicit)
        with self.assertRaises(ValueError):self.task(s,4,'net')
        self.assertEqual(s.bank.authority['A']['examples'],explicit)
        self.assertEqual(s.retirement_events,[])
        self.assertEqual(self.task(s,5,'net')['action'],'delegate')
        self.assertEqual(s.bank.authority['A']['examples'],explicit)

    def test_manual_calibration_not_erased_on_shape_change(self):
        s=self.session();s.permit('A','1')
        for n in range(1,3):self.task(s,n)
        s.authorize('A','1',deepcopy(s.bank.authority['A']['examples']))
        before=deepcopy(s.bank.authority)
        with self.assertRaisesRegex(ValueError,'Host calibration schema'):
            s.run('A','1',{'id':'x','new':'5 g'},'x',allowance=12,
                  acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(s.bank.authority,before)
        self.assertEqual(s.worker_calls,2)

    def test_missing_verdict_never_invalidates_learned_calibration(self):
        s=self.session();s.permit('A','1')
        for n in range(1,4):self.task(s,n)
        before=deepcopy(s.bank.authority)
        s.evaluate=lambda *a:None
        with self.assertRaises(ValueError):self.task(s,4,'net')
        self.assertEqual(s.bank.authority,before)
        self.assertEqual(s.retirement_events,[])

if __name__=='__main__':unittest.main()
