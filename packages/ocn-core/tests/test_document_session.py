import hashlib,tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.routes={};self.text='City Taza.'
        for name in ('primary','mirror'):
            root=self.base/name;root.mkdir();(root/'d.txt').write_text(self.text)
            adapter=DocumentAdapter(root,self.base/(name+'.json'));adapter.bind('D','d.txt');self.routes[name]=adapter
    def worker(self,q,fields,identity,text):
        return dict(observations=[dict(field=f,source_id=identity,sha256=hashlib.sha256(text.encode()).hexdigest(),
            status='value',value='Taza',quote=text) for f in fields],usage={'model_calls':1})
    def create(self,**kw):return DocumentSession(self.routes,self.worker,lambda:'fixture',**kw)
    def answer(self,s):return s.answer('City?',{'city':'Copy city'},('D',))
    def test_move_fallback_and_cache(self):
        s=self.create();self.answer(s)
        (self.base/'primary/d.txt').rename(self.base/'primary/moved.txt')
        self.assertEqual(self.answer(s)['source_paths']['D'],'primary/moved.txt')
        (self.base/'primary/moved.txt').unlink()
        r=self.answer(s);self.assertEqual(r['source_paths']['D'],'mirror/d.txt')
        self.assertEqual(s.calls,1)
        (self.base/'mirror/d.txt').write_text('Changed.')
        with self.assertRaises(ValueError):self.answer(s)
        self.assertEqual(s.calls,1)
    def test_calls_and_attempts_are_bounded(self):
        s=self.create(max_model_calls=1,max_requests=2);self.answer(s)
        with self.assertRaises(RuntimeError):s.answer('Another question',{'city':'Copy city'},('D',))
        self.assertEqual(s.calls,1)
        with self.assertRaises(RuntimeError):self.answer(s)
    def test_invalid_request_consumes_attempt_but_not_worker(self):
        s=self.create(max_requests=1)
        with self.assertRaises(ValueError):s.answer('',{'city':'City'},('D',))
        self.assertEqual(s.calls,0)
        with self.assertRaises(RuntimeError):self.answer(s)
    def invalid(self,*args):
        result=self.worker(*args);result['observations'][0]['quote']='fabricated'
        result['usage'].update(input_tokens=10,output_tokens=5)
        return result
    def test_fallback_charges_both_attempts_and_cache_reuses_valid_result(self):
        s=DocumentSession(self.routes,self.invalid,lambda:'p',fallback_worker=self.worker,fallback_revision=lambda:'f',max_model_calls=2)
        result=self.answer(s);self.assertEqual(result['values'],{'city':'Taza'})
        self.assertEqual(result['session']['model_calls'],2)
        trace=s.attempts();self.assertEqual([x['status'] for x in trace],['invalid','validated'])
        self.assertEqual(trace[0]['usage']['input_tokens'],10)
        trace[0]['status']='tampered';self.assertEqual(s.attempts()[0]['status'],'invalid')
        self.assertEqual(self.answer(s)['session']['model_calls'],0)
        self.assertEqual(s.calls,2)
    def test_no_fallback_after_budget_exhaustion_and_invalid_not_cached(self):
        def forbidden(*args):self.fail('Fallback bypassed budget')
        s=DocumentSession(self.routes,self.invalid,lambda:'p',fallback_worker=forbidden,fallback_revision=lambda:'f',max_model_calls=1)
        with self.assertRaisesRegex(RuntimeError,'budget'):self.answer(s)
        self.assertEqual(s.calls,1);self.assertEqual(s.cache.stats()['entries'],0)
        self.assertEqual(len(s.attempts()),1)
    def test_fallback_failure_and_transport_errors_keep_costs(self):
        s=DocumentSession(self.routes,self.invalid,lambda:'p',fallback_worker=self.invalid,fallback_revision=lambda:'f')
        with self.assertRaises(ValueError):self.answer(s)
        self.assertEqual(s.calls,2);self.assertEqual(s.cache.stats()['entries'],0)
        def broken(*args):raise TimeoutError('network')
        s=DocumentSession(self.routes,broken,lambda:'p',fallback_worker=self.worker,fallback_revision=lambda:'f')
        with self.assertRaises(TimeoutError):self.answer(s)
        self.assertEqual(s.calls,1);self.assertEqual(s.attempts()[0]['status'],'error')
    def test_fallback_revision_change_invalidates_cached_result(self):
        revision=['f1']
        s=DocumentSession(self.routes,self.invalid,lambda:'p',fallback_worker=self.worker,fallback_revision=lambda:revision[0])
        self.answer(s);revision[0]='f2';self.answer(s)
        self.assertEqual(s.calls,4)
    def test_persistent_budget_survives_new_session_and_charges_fallback(self):
        from ocn_core.model_budget import PersistentAttemptBudget
        directory=self.base/'budget';directory.mkdir()
        budget=PersistentAttemptBudget.create(directory,2)
        s=DocumentSession(self.routes,self.invalid,lambda:'p',fallback_worker=self.worker,
            fallback_revision=lambda:'f',attempt_budget=budget)
        self.answer(s);self.assertEqual(budget.snapshot()['used'],2)
        reopened=PersistentAttemptBudget(directory,2)
        second=DocumentSession(self.routes,self.worker,lambda:'p',attempt_budget=reopened)
        with self.assertRaisesRegex(RuntimeError,'Persistent'):self.answer(second)
        self.assertEqual(second.calls,0)
        self.assertEqual(self.answer(s)['session']['model_calls'],0)
    def test_failed_durable_reservation_never_calls_worker(self):
        from ocn_core.model_budget import PersistentAttemptBudget
        from unittest.mock import patch
        directory=self.base/'budget';directory.mkdir();budget=PersistentAttemptBudget.create(directory,2)
        def forbidden(*args):self.fail('Worker invoked without durable reservation')
        s=DocumentSession(self.routes,forbidden,lambda:'p',attempt_budget=budget)
        with patch.object(budget,'reserve',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.answer(s)
        self.assertEqual(s.calls,0)

    def test_valid_ambiguity_does_not_trigger_fallback(self):
        def ambiguous(*args):
            r=self.worker(*args);r['observations'][0].update(status='ambiguous',value=None);return r
        def forbidden(*args):self.fail('Ambiguity was treated as retry permission')
        s=DocumentSession(self.routes,ambiguous,lambda:'p',fallback_worker=forbidden,fallback_revision=lambda:'f')
        self.assertTrue(self.answer(s)['abstain']);self.assertEqual(s.calls,1)

if __name__=='__main__':unittest.main()
