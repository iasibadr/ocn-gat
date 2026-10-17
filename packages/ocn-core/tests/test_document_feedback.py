"""Verified feedback on real file sessions; fixtures are not learned semantics."""
import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession
from ocn_core.document_feedback import FeedbackDocumentSession
from ocn_core.experience_memory import ExperienceMemory

class Tests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);docs=self.root/'docs';docs.mkdir();(docs/'d.txt').write_text('City Taza.')
        adapter=DocumentAdapter(docs,self.root/'pins.json');adapter.bind('D','d.txt')
        def worker(q,fields,identity,text):
            return dict(observations=[dict(source_id=identity,field='city',sha256=hashlib.sha256(text.encode()).hexdigest(),status='value',value='Taza',quote=text)],usage={'model_calls':1})
        self.worker=worker;self.routes={'local':adapter}
        self.session=DocumentSession(self.routes,worker,lambda:'fixture')
        self.memory=ExperienceMemory.create(self.root/'experience.sqlite',contract_id='evaluation-v1',actions=['policy'])
        self.request=dict(question='City?',fields={'city':'Copy city'},document_ids=('D',))
    def bridge(self,evaluate):
        return FeedbackDocumentSession(self.session,self.memory,action='policy',context=lambda request:'document',evaluate=evaluate)
    def verdict(self,*args):return dict(success=True,quality=1,interventions=0,evidence_id='fixture-label-1')
    def test_verified_feedback_and_cache_cost(self):
        b=self.bridge(self.verdict)
        r=b.answer(self.request);self.assertEqual(r['feedback'],'recorded');self.assertEqual(r['model_calls'],1)
        self.assertGreater(r['environment']['route_attempts'],0)
        self.assertEqual(r['environment']['route_failures'],0)
        import json
        with self.memory.connect() as db:
            stored=json.loads(db.execute('SELECT payload FROM outcomes ORDER BY seq LIMIT 1').fetchone()[0])
        self.assertEqual(stored['environment']['route_attempts'],r['environment']['route_attempts'])
        r=b.answer(self.request);self.assertEqual(r['model_calls'],0)
        self.assertEqual(self.memory.estimate('document','policy')['observations'],2)
    def test_fallback_cost_is_attributed_to_whole_policy(self):
        def bad(*args):
            r=self.worker(*args);r['observations'][0]['quote']='fake';return r
        self.session=DocumentSession(self.routes,bad,lambda:'bad',fallback_worker=self.worker,fallback_revision=lambda:'good')
        receipt=self.bridge(self.verdict).answer(self.request)
        self.assertEqual(receipt['model_calls'],2)
        import json
        with self.memory.connect() as db:
            value=json.loads(db.execute('SELECT payload FROM outcomes').fetchone()[0])
        self.assertEqual(value['cost'],2)

    def test_no_semantic_reward_without_evaluation(self):
        for verdict in [None,{'success':True},dict(success=True,quality=2,interventions=0,evidence_id='bad')]:
            r=self.bridge(lambda *args:verdict).answer(self.request)
            self.assertEqual(r['feedback'],'unverified')
        self.assertEqual(self.memory.estimate('document','policy')['observations'],0)
    def test_storage_failure_blocks_execution_until_retry(self):
        b=self.bridge(self.verdict)
        with patch.object(self.memory,'record',side_effect=OSError('disk')):
            r=b.answer(self.request);self.assertEqual(r['feedback'],'pending')
        before=self.session.calls
        with self.assertRaises(RuntimeError):b.answer(self.request)
        receipt=b.retry_feedback();self.assertEqual(receipt['event_id'],r['event_id'])
        self.assertEqual(self.session.calls,before)
        self.assertEqual(self.memory.estimate('document','policy')['observations'],1)
    def test_partial_commit_retry_is_idempotent(self):
        b=self.bridge(self.verdict);real=self.memory.record
        def partial(**kwargs):real(**kwargs);raise OSError('reply lost')
        with patch.object(self.memory,'record',side_effect=partial):self.assertEqual(b.answer(self.request)['feedback'],'pending')
        b.retry_feedback();self.assertEqual(self.memory.estimate('document','policy')['observations'],1)
    def test_error_not_automatically_a_negative_label(self):
        b=self.bridge(lambda *args:None)
        (self.root/'docs/d.txt').unlink()
        r=b.answer(self.request);self.assertEqual(r['outcome']['status'],'error');self.assertEqual(r['feedback'],'unverified')
        self.assertGreater(r['environment']['route_failures'],0)
        self.assertEqual(self.memory.estimate('document','policy')['observations'],0)

if __name__=='__main__':unittest.main()
