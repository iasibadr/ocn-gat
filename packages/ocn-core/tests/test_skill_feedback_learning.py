import unittest
from ocn_core.skill_session import SkillSession


class FeedbackLearningTests(unittest.TestCase):
    def session(self):
        self.seen=[]
        def worker(c,r,record,i,examples):
            self.seen.append(examples)
            return {'value': record['mass']}
        return SkillSession(worker,lambda c,r,s,i,o:o['value']==s['mass'],learn_from_feedback=True)

    def task(self,s,i,n,revision='1'):
        return s.run('A',revision,{'id':i,'mass':f'{n} g'},i,
                     allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)

    def test_verified_experience_becomes_reusable_procedure(self):
        s=self.session();s.permit('A','1')
        first=self.task(s,'a',10);second=self.task(s,'b',20);third=self.task(s,'c',30)
        fourth=self.task(s,'d',40)
        self.assertEqual([x['action'] for x in (first,second,third,fourth)],
                         ['delegate','delegate','acquire_apply','apply'])
        self.assertEqual(second['learning'],'calibration_ready')
        self.assertEqual(s.worker_calls,2)
        self.assertEqual(self.seen,[[],[]])
        self.assertEqual(s.examples,{})

    def test_failed_or_nonboolean_verdict_cannot_train(self):
        s=self.session();s.permit('A','1')
        for verdict in (False,None):
            s.evaluate=lambda *args:verdict
            with self.assertRaises(ValueError):self.task(s,'a',10)
            self.assertEqual(s.examples,{})
            self.assertEqual(s.bank.authority,{})

    def test_diversity_and_permission_revision_boundaries(self):
        s=self.session()
        with self.assertRaises(ValueError):self.task(s,'a',10)
        self.assertEqual(s.worker_calls,0)
        s.permit('A','1');self.task(s,'a',10)
        self.assertEqual(self.task(s,'a',20)['learning'],'insufficient_diversity')
        self.assertEqual(self.task(s,'b',10)['learning'],'insufficient_diversity')
        s.permit('A','1');self.assertEqual(len(s.examples['A']),1)
        s.permit('A','2');self.assertEqual(s.examples,{})
        with self.assertRaises(ValueError):self.task(s,'c',30)
        self.assertEqual(self.task(s,'c',30,'2')['learning'],'observation_retained')

    def test_permissions_share_bound_with_manual_calibration(self):
        s=self.session()
        for n in range(8):s.permit(str(n),'1')
        from ocn_core.mass_read_skill import _validate_examples
        examples=[dict(record={'id':i,'mass':f'{n} g'},identity=i,expected=f'{n} g')
                  for i,n in [('a',10),('b',20)]]
        _validate_examples(examples)
        with self.assertRaises(ValueError):s.authorize('extra','1',examples)
        with self.assertRaises(ValueError):s.permit('extra','1')

if __name__=='__main__':unittest.main()
