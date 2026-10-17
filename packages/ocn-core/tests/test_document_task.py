import hashlib,tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession
from ocn_core.document_task import DocumentTask


class DocumentTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);docs=self.root/'docs';docs.mkdir()
        self.path=docs/'a.txt';self.path.write_text('City Taza.')
        self.adapter=DocumentAdapter(docs,self.root/'pins.json');self.adapter.bind('a','a.txt')
        self.value='Taza';self.status='value'
        def worker(q,fields,i,text):
            return dict(observations=[dict(source_id=i,field=f,sha256=hashlib.sha256(text.encode()).hexdigest(),
                status=self.status,value=self.value if self.status=='value' else None,
                quote=text if self.status!='absent' else None) for f in fields],usage={})
        self.session=DocumentSession({'local':self.adapter},worker,lambda:'fixture',max_model_calls=8)

    def ask(self,t):return t.answer('Which city?',{'city':'Actual city name'},('a',))

    def test_coverage_without_checker_is_not_completion(self):
        r=self.ask(DocumentTask(self.session))
        self.assertEqual(r['completion']['status'],'needs_verification')
        self.assertEqual(r['values'],{});self.assertEqual(r['candidate_values'],{'city':'Taza'})
        self.assertFalse(r['completion']['documentary_task_completed'])

    def test_confirmed_answer_does_not_authorize_action(self):
        t=DocumentTask(self.session,completion_check=lambda q,f,r:r['values']=={'city':'Taza'},checker_id='host-v1')
        r=self.ask(t)
        self.assertTrue(r['completion']['documentary_task_completed'])
        self.assertEqual(r['values'],{'city':'Taza'})
        self.assertFalse(r['completion']['action_authorized'])

    def test_absent_field_never_calls_confirmation(self):
        self.status='absent'
        t=DocumentTask(self.session,completion_check=lambda *a:self.fail('Missing fields must block confirmation'),checker_id='host')
        r=self.ask(t)
        self.assertEqual(r['completion']['status'],'insufficient_evidence')
        self.assertEqual(r['completion']['blockers'],{'city':['no_established_value']})
        self.assertFalse(r['completion']['documentary_task_completed'])

    def test_rejected_extraction_is_cleared_and_can_be_retried(self):
        self.value='Paris'
        t=DocumentTask(self.session,completion_check=lambda q,f,r:r['values']=={'city':'Taza'},checker_id='host')
        r=self.ask(t)
        self.assertEqual(r['completion']['status'],'verification_failed')
        self.assertEqual(self.session.cache.stats()['entries'],0)
        self.value='Taza'
        self.assertTrue(self.ask(t)['completion']['documentary_task_completed'])
        self.assertEqual(self.session.calls,2)

    def test_unknown_and_invalid_verdict_are_not_success(self):
        t=DocumentTask(self.session,completion_check=lambda *a:None,checker_id='host')
        self.assertFalse(self.ask(t)['completion']['documentary_task_completed'])
        t=DocumentTask(self.session,completion_check=lambda *a:1,checker_id='host')
        with self.assertRaises(ValueError):self.ask(t)

    def test_checker_cannot_mutate_result_and_sources_are_revalidated(self):
        def checker(q,f,r):
            r['values']['city']='Injected';f.clear()
            return True
        r=self.ask(DocumentTask(self.session,completion_check=checker,checker_id='host'))
        self.assertEqual(r['values'],{'city':'Taza'})
        def changed(*a):self.path.write_text('City Paris.');return True
        with self.assertRaises(ValueError):self.ask(DocumentTask(self.session,completion_check=changed,checker_id='host'))

    def test_reentrant_completion_is_rejected(self):
        def checker(*a):
            with self.assertRaisesRegex(RuntimeError,'busy'):self.ask(t)
            return True
        t=DocumentTask(self.session,completion_check=checker,checker_id='host')
        self.assertTrue(self.ask(t)['completion']['documentary_task_completed'])


if __name__=='__main__':unittest.main()
