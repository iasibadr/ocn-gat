import unittest
from ocn_core.skill_session import SkillSession

class SkillRecoveryTests(unittest.TestCase):
    def setup_session(self,**kwargs):
        self.calls=[];self.bad=False
        def worker(c,r,s,i,e):
            self.calls.append((i,e))
            return {'value':'wrong' if self.bad else s[s['current']]}
        s=SkillSession(worker,lambda c,r,d,i,o:o['value']==d[d['current']],
            learn_from_feedback=True,skill_kind='text',retry_rejected_skill=kwargs.pop('retry',True),**kwargs)
        s.permit('A','1')
        for i in range(3):self.ask(s,str(i),'first')
        return s
    def ask(self,s,i,current,allowance=12):
        return s.run('A','1',{'id':i,'first':'City '+i,'second':'Other '+i,'current':current},i,
            allowance=allowance,acquisition_cost=3,application_cost=1,delegation_cost=8)
    def test_recover_once_and_learn_only_verified_new_value(self):
        s=self.setup_session();r=self.ask(s,'3','second')
        self.assertEqual(r['action'],'recover_delegate');self.assertEqual(r['declared_cost'],9)
        self.assertEqual(r['recovery']['attempts'],1);self.assertEqual(s.worker_calls,3)
        self.assertEqual(s.requests,4);self.assertEqual(self.calls[-1],('3',[]))
        self.assertEqual(s.examples['A'][0]['expected'],'Other 3')
        self.ask(s,'4','second');r=self.ask(s,'5','second')
        self.assertEqual(r['action'],'acquire_apply');self.assertEqual(r['output']['value'],'Other 5')
    def test_default_no_retry_and_allowance_no_overrun(self):
        for options,allowance in [({'retry':False},12),({},8),({'max_worker_calls':2},12)]:
            limit=options.pop('max_worker_calls',None)
            s=self.setup_session(**options)
            if limit is not None:s.max_worker_calls=limit
            with self.assertRaisesRegex(ValueError,'semantic'):self.ask(s,'3','second',allowance)
            self.assertEqual(s.worker_calls,2);self.assertNotIn('A',s.learned_calibrations)
    def test_failed_recovery_is_charged_and_never_trains(self):
        s=self.setup_session();self.bad=True
        with self.assertRaisesRegex(ValueError,'Recovery output'):self.ask(s,'3','second')
        self.assertEqual(s.worker_calls,3);self.assertNotIn('A',s.examples)
    def test_invalid_verdict_does_not_trigger_retry(self):
        s=self.setup_session();s.evaluate=lambda *args:None
        with self.assertRaisesRegex(ValueError,'boolean'):self.ask(s,'3','second')
        self.assertEqual(s.worker_calls,2)
    def test_worker_exception_is_charged_and_not_retried(self):
        s=self.setup_session()
        def fail(*args):raise RuntimeError('worker down')
        s.worker=fail
        with self.assertRaisesRegex(RuntimeError,'worker down'):self.ask(s,'3','second')
        self.assertEqual(s.worker_calls,3);self.assertNotIn('A',s.examples)
    def test_host_calibration_is_not_replaced_or_recovered(self):
        s=self.setup_session();authority=s.bank.authority['A']
        s.authorize('A','1',authority['examples'])
        with self.assertRaisesRegex(ValueError,'semantic'):self.ask(s,'3','second')
        self.assertEqual(s.worker_calls,2);self.assertEqual(s.bank.authority['A'],authority)

if __name__=='__main__':unittest.main()
