import unittest
from ocn_core.skill_session import SkillSession


class SchemaAdaptationTests(unittest.TestCase):
    def session(self):
        def worker(c,r,s,i,e):return {'value':s.get('mass',s.get('net'))}
        s=SkillSession(worker,lambda c,r,s,i,o:o['value']==s.get('mass',s.get('net')),
                       learn_from_feedback=True,adapt_schema_changes=True,
                       identity_guard=lambda c,r,s,i:s.get('id')==i)
        s.permit('A','1')
        return s

    def task(self,s,i,field='mass',identity=None):
        return s.run('A','1',{'id':str(i),field:f'{i*10} g'},identity or str(i),
                     allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)

    def test_relearn_without_revision_signal(self):
        s=self.session()
        rows=[self.task(s,i,'mass' if i<=4 else 'net') for i in range(1,9)]
        self.assertEqual([r['action'] for r in rows],
                         ['delegate','delegate','acquire_apply','apply']*2)
        self.assertEqual(s.worker_calls,4)
        self.assertEqual(len(s.schema_events),1)
        self.assertEqual(s.permissions,{'A':'1'})

    def test_wrong_identity_cannot_erase_method_or_call_worker(self):
        s=self.session()
        for i in range(1,4):self.task(s,i)
        before=s.bank.entries['A'];calls=s.worker_calls
        with self.assertRaisesRegex(ValueError,'identity'):self.task(s,4,'net',identity='other')
        self.assertEqual(s.bank.entries['A'],before)
        self.assertEqual(s.worker_calls,calls)
        self.assertEqual(s.schema_events,[])

    def test_change_during_initial_collection_discards_old_sample(self):
        s=self.session();self.task(s,1);self.task(s,2,'net');self.task(s,3,'net')
        self.assertEqual(self.task(s,4,'net')['action'],'acquire_apply')
        self.assertEqual(s.worker_calls,3)
        self.assertEqual(len(s.schema_events),1)

    def test_unsupported_shape_does_not_mutate_learned_method(self):
        s=self.session()
        for i in range(1,4):self.task(s,i)
        before=s.bank.entries['A']
        with self.assertRaises(ValueError):
            s.run('A','1',{'id':'x','mass':[]},'x',allowance=12,
                  acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(s.bank.entries['A'],before)
        self.assertEqual(s.worker_calls,2)

    def test_requires_explicit_guard_and_learning(self):
        with self.assertRaises(ValueError):
            SkillSession(lambda *a:None,lambda *a:True,adapt_schema_changes=True)

if __name__=='__main__':unittest.main()
