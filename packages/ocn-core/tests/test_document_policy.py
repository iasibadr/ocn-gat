import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_policy import PolicyDocumentSession

class Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        docs=self.root/'docs';docs.mkdir();(docs/'d.txt').write_text('Options: A and B.')
        adapter=DocumentAdapter(docs,self.root/'pins.json');adapter.bind('D','d.txt');self.routes={'local':adapter}
        self.target='A';self.verdict=True;self.seen=[]
        def worker(value):
            def extract(q,f,i,t):
                self.seen.append(value)
                return dict(observations=[dict(source_id=i,field='choice',sha256=hashlib.sha256(t.encode()).hexdigest(),status='value',value=value,quote=t)],usage={'model_calls':1})
            return extract
        self.policies={n:(worker(n),n+'-v1',worker(n),n+'-v1') for n in ('A','B')}
    def evaluate(self,request,outcome):
        if not self.verdict:return None
        success=outcome['status']=='returned' and outcome['response']['values']=={'choice':self.target}
        return dict(success=success,quality=int(success),interventions=0,evidence_id='fixture-authorized-target')
    def create(self,**kw):
        return PolicyDocumentSession(self.routes,self.root/'memory.sqlite',policies=self.policies,
            context=lambda r:'same-observable-context',evaluate=self.evaluate,evaluation_contract='fixture-v1',**kw)
    def answer(self,s):return s.answer(dict(question='Choose an option',fields={'choice':'Option'},document_ids=('D',)))
    def test_learns_verified_reward_then_reacts_to_reversal(self):
        s=self.create(max_model_calls=64,max_requests=64,probe_every=4)
        first=[self.answer(s) for _ in range(12)]
        self.assertEqual([r['action'] for r in first[:3]],['A','B','A'])
        self.assertTrue(all(r['action']=='A' for r in first if r['selection']['reason']=='observed_reward'))
        self.target='B'
        later=[self.answer(s) for _ in range(20)]
        exploit=[r for r in later if r['selection']['reason']=='observed_reward']
        self.assertTrue(all(r['action']=='B' for r in exploit[-5:]))
        self.assertEqual(s.memory.estimate('same-observable-context','B')['observations']>0,True)
    def test_unverified_results_do_not_create_preferences(self):
        self.verdict=False;s=self.create(max_requests=6)
        results=[self.answer(s) for _ in range(6)]
        self.assertEqual([r['action'] for r in results],['A','B','A','B','A','B'])
        self.assertTrue(all(r['feedback']=='unverified' for r in results))
    def test_one_shared_budget_across_policies(self):
        s=self.create(max_model_calls=1,max_requests=2)
        self.answer(s);r=self.answer(s)
        self.assertEqual(s.session.calls,1);self.assertEqual(r['outcome']['status'],'error')
        with self.assertRaises(RuntimeError):self.answer(s)
    def test_pending_feedback_blocks_policy_change(self):
        s=self.create()
        with patch.object(s.memory,'record',side_effect=OSError('disk')):r=self.answer(s)
        self.assertEqual(r['feedback'],'pending');before=s.session.calls
        with self.assertRaises(RuntimeError):self.answer(s)
        s.retry_feedback();self.assertEqual(s.session.calls,before)
    def test_policy_identity_prevents_cross_policy_cache_hit(self):
        s=self.create();self.answer(s);self.answer(s);self.answer(s)
        self.assertEqual(self.seen,['A','B']);self.assertEqual(s.session.calls,2)

if __name__=='__main__':unittest.main()
