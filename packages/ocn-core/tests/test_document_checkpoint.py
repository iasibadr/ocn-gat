import hashlib,tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession
from ocn_core.document_checkpoint import CheckpointedDocumentSession
from ocn_core.model_budget import PersistentAttemptBudget

class Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        docs=self.root/'docs';docs.mkdir();(docs/'d.txt').write_text('City Taza.')
        adapter=DocumentAdapter(docs,self.root/'pins.json');adapter.bind('D','d.txt');self.routes={'local':adapter}
        (self.root/'budget').mkdir();self.budget=PersistentAttemptBudget.create(self.root/'budget',8)
        self.calls=0;self.revision='v1';self.request=dict(question='City?',fields={'city':'Copy'},document_ids=('D',))
    def worker(self,q,f,i,t):
        self.calls+=1
        return dict(observations=[dict(source_id=i,field='city',sha256=hashlib.sha256(t.encode()).hexdigest(),status='value',value='Taza',quote=t)],usage={'model_calls':1})
    def session(self,worker=None):return DocumentSession(self.routes,worker or self.worker,lambda:self.revision,attempt_budget=self.budget)
    def create(self,session=None,**kw):return CheckpointedDocumentSession.create(self.root/'journal',session or self.session(),contract='host-v1',**kw)
    def test_reopen_completed_result_is_historical_without_worker_or_reads(self):
        journal=self.create();first=journal.execute('a'*32,self.request);self.assertFalse(first['historical'])
        (self.root/'docs/d.txt').unlink()
        reopened=CheckpointedDocumentSession(self.root/'journal',self.session(),contract='host-v1')
        result=reopened.execute('a'*32,self.request)
        self.assertTrue(result['historical']);self.assertEqual(result['result'],first['result']);self.assertEqual(self.calls,1)
    def test_uncertain_attempt_refuses_reexecution_after_reopen(self):
        def broken(*args):self.calls+=1;raise TimeoutError('uncertain')
        journal=self.create(self.session(broken))
        with self.assertRaises(TimeoutError):journal.execute('a'*32,self.request)
        reopened=CheckpointedDocumentSession(self.root/'journal',self.session(),contract='host-v1')
        self.assertEqual(reopened.recover('a'*32,self.request)['state'],'unresolved')
        with self.assertRaisesRegex(RuntimeError,'Unresolved'):reopened.execute('a'*32,self.request)
        self.assertEqual(self.calls,1)
    def test_same_id_cannot_mean_different_request(self):
        journal=self.create();journal.execute('a'*32,self.request)
        with self.assertRaises(ValueError):journal.execute('a'*32,dict(self.request,question='Different'))
    def test_persistent_request_bound_and_policy_revision(self):
        journal=self.create(max_requests=1);journal.execute('a'*32,self.request)
        with self.assertRaises(RuntimeError):journal.execute('b'*32,self.request)
        self.revision='v2'
        with self.assertRaises(ValueError):journal.recover('a'*32,self.request)
    def test_intent_write_failure_prevents_worker(self):
        from unittest.mock import patch
        journal=self.create()
        with patch.object(journal,'_publish',side_effect=OSError('disk')):
            with self.assertRaises(OSError):journal.execute('a'*32,self.request)
        self.assertEqual(self.calls,0)
    def test_result_write_failure_leaves_unresolved_not_retryable(self):
        from unittest.mock import patch
        journal=self.create();original=journal._publish
        def publish(path,value):
            if path.name.endswith('.result.json'):raise OSError('result publication failed')
            original(path,value)
        with patch.object(journal,'_publish',side_effect=publish):
            with self.assertRaises(OSError):journal.execute('a'*32,self.request)
        self.assertEqual(journal.recover('a'*32,self.request)['state'],'unresolved')
        with self.assertRaises(RuntimeError):journal.execute('a'*32,self.request)
        self.assertEqual(self.calls,1)
    def memory(self):
        from ocn_core.experience_memory import ExperienceMemory
        return ExperienceMemory.create(self.root/'memory.sqlite',contract_id='rubric-v1',actions=['policy'])
    def verdict(self):return dict(success=True,quality=1,interventions=0,evidence_id='verified-fixture-1')
    def test_durable_feedback_reopens_without_task_reexecution(self):
        from unittest.mock import patch
        journal=self.create();journal.execute('a'*32,self.request);memory=self.memory()
        with patch.object(memory,'record',side_effect=OSError('disk')):
            with self.assertRaises(OSError):journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict=self.verdict())
        reopened=CheckpointedDocumentSession(self.root/'journal',self.session(),contract='host-v1')
        self.assertTrue(reopened.retry_feedback('a'*32,self.request,memory)['inserted'])
        self.assertFalse(reopened.retry_feedback('a'*32,self.request,memory)['inserted'])
        self.assertEqual(memory.estimate('docs','policy')['observations'],1);self.assertEqual(self.calls,1)
    def test_feedback_partial_commit_is_not_double_rewarded(self):
        from unittest.mock import patch
        journal=self.create();journal.execute('a'*32,self.request);memory=self.memory();original=memory.record
        def committed(**kwargs):original(**kwargs);raise OSError('lost acknowledgement')
        with patch.object(memory,'record',side_effect=committed):
            with self.assertRaises(OSError):journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict=self.verdict())
        self.assertFalse(journal.retry_feedback('a'*32,self.request,memory)['inserted'])
        self.assertEqual(memory.estimate('docs','policy')['observations'],1)
    def test_uncertain_feedback_publication_must_sync_before_memory_insert(self):
        from unittest.mock import patch
        journal=self.create();journal.execute('a'*32,self.request);memory=self.memory()
        with patch('ocn_core.document_checkpoint.sync_directory',side_effect=OSError('fsync')):
            with self.assertRaises(OSError):journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict=self.verdict())
            with self.assertRaises(OSError):journal.retry_feedback('a'*32,self.request,memory)
        self.assertEqual(memory.estimate('docs','policy')['observations'],0)
        self.assertTrue(journal.retry_feedback('a'*32,self.request,memory)['inserted'])
    def test_conflicting_verdict_refused_before_memory_change(self):
        journal=self.create();journal.execute('a'*32,self.request);memory=self.memory()
        journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict=self.verdict())
        with self.assertRaises(ValueError):journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict=dict(self.verdict(),success=False))
        self.assertEqual(memory.estimate('docs','policy')['expected_return'],1)
    def test_unstarted_task_and_invalid_verdict_cannot_enter_memory(self):
        journal=self.create();memory=self.memory()
        with self.assertRaises(ValueError):journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict=self.verdict())
        journal.execute('a'*32,self.request)
        with self.assertRaises(ValueError):journal.record_feedback('a'*32,self.request,memory,action='policy',context='docs',verdict={'success':True})
        self.assertFalse((self.root/'journal'/('a'*32+'.feedback.json')).exists())
        self.assertEqual(memory.estimate('docs','policy')['observations'],0)
    def test_missing_request_is_not_started(self):
        self.assertEqual(self.create().recover('a'*32,self.request)['state'],'not_started')

if __name__=='__main__':unittest.main()
