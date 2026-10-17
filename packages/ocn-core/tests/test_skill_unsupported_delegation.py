import unittest
from copy import deepcopy
from ocn_core.skill_session import SkillSession


class UnsupportedDelegationTests(unittest.TestCase):
    def session(self):
        def worker(c,r,s,i,e):
            value=s['mass'][0] if type(s['mass']) is list else s['mass']
            return {'value':value}
        s=SkillSession(worker,lambda c,r,s,i,o:o['value']==f'{int(i)*100} g',
            learn_from_feedback=True,adapt_schema_changes=True,delegate_unsupported_shapes=True,
            identity_guard=lambda c,r,s,i:s.get('id')==i)
        s.permit('A','1');return s

    def task(self,s,n,unsupported=False,**kwargs):
        value=f'{n*100} g';record={'id':str(n),'mass':[value] if unsupported else value}
        params=dict(allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)
        params.update(kwargs)
        return s.run('A','1',record,str(n),**params)

    def test_delegate_outside_grammar_then_reuse_preserved_method(self):
        s=self.session()
        for n in range(1,4):self.task(s,n)
        authority=deepcopy(s.bank.authority);entry=s.bank.entries['A']
        row=self.task(s,4,True)
        self.assertEqual(row['action'],'delegate')
        self.assertEqual(row['learning'],'unsupported_observation')
        self.assertEqual(s.bank.authority,authority)
        self.assertEqual(s.bank.entries['A'],entry)
        self.assertEqual(self.task(s,5)['action'],'apply')
        self.assertEqual(s.worker_calls,3)
        self.assertEqual(s.schema_events,[])

    def test_no_training_on_unrepresentable_records(self):
        s=self.session()
        for n in range(1,4):self.task(s,n,True)
        self.assertEqual(s.bank.authority,{})
        self.assertEqual(s.examples,{})

    def test_declared_allowance_and_identity_still_enforced(self):
        s=self.session()
        with self.assertRaises(RuntimeError):self.task(s,1,True,allowance=7)
        with self.assertRaisesRegex(ValueError,'identity'):
            s.run('A','1',{'id':'wrong','mass':['100 g']},'1',allowance=12,
                  acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(s.worker_calls,0)

    def test_byte_limit_still_enforced(self):
        s=self.session()
        with self.assertRaisesRegex(ValueError,'byte budget'):
            s.run('A','1',{'id':'1','mass':['x'*17000]},'1',allowance=12,
                  acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(s.worker_calls,0)

    def test_rejected_worker_output_is_not_a_success(self):
        s=self.session();s.worker=lambda *args:{'value':'wrong'}
        with self.assertRaisesRegex(ValueError,'semantic'):self.task(s,1,True)
        self.assertEqual(s.worker_calls,1)
        self.assertEqual(s.examples,{})

if __name__=='__main__':unittest.main()
