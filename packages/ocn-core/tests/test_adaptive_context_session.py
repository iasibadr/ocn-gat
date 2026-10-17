import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.adaptive_context_session import AdaptiveContextSession
from ocn_core.local_evidence_context import LocalEvidenceContextWorker
from ocn_core.document_adapter import DocumentAdapter

CAPACITY='Prompt exceeds maximum conservative context allowance'
class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.adapter=DocumentAdapter(self.docs,self.root/'pins.json')
        self.model=patch('ocn_core.local_evidence_context.require_model',return_value={'digest':'fixture'})
        self.model.start();self.addCleanup(self.model.stop)
        self.worker=LocalEvidenceContextWorker('fixture',max_calls=2)
        self.payloads=[]
        def answer(payload):
            if self.worker.calls>=self.worker.max_calls:raise RuntimeError('Model budget exhausted')
            self.payloads.append(payload)
            if sum(len(p['text']) for p in payload['paragraphs'])>200:raise ValueError(CAPACITY)
            self.worker._attempts.append(dict(stage='answer'))
            return {'day':dict(status='supported',answer='lundi',references=[payload['paragraphs'][0]['id']])}
        self.worker.answer=answer
    def enroll(self,text):
        (self.docs/'a.md').write_text(text);self.adapter.bind('a','a.md')
    def ask(self,s):return s.answer('Livraison ZP21 ?',{'day':'Jour de livraison ZP21'},('a',))
    def large(self):return 'ZP21 livraison lundi.\n\n'+'Archive sans rapport. '*20

    def test_small_uses_full_only(self):
        self.enroll('ZP21 livraison lundi.');s=AdaptiveContextSession(self.adapter,self.worker)
        result=self.ask(s)
        self.assertEqual(result['context_routing']['routes'],['full'])
        self.assertEqual(result['context_routing']['model_calls'],1)
        self.assertIsNone(result['selection'])

    def test_large_falls_back_without_failed_model_call_and_reuses_cache(self):
        self.enroll(self.large());s=AdaptiveContextSession(self.adapter,self.worker,max_requests=2)
        first=self.ask(s);(self.docs/'a.md').rename(self.docs/'moved.md');second=self.ask(s)
        self.assertEqual(first['context_routing']['routes'],['full','unique-coverage'])
        self.assertEqual(first['context_routing']['model_calls'],1)
        self.assertTrue(second['session']['selection_cache_hit'])
        self.assertEqual(self.worker.calls,2)
        with self.assertRaisesRegex(RuntimeError,'request budget'):self.ask(s)

    def test_changed_source_during_refusal_does_not_bypass_version_guard(self):
        self.enroll(self.large());s=AdaptiveContextSession(self.adapter,self.worker)
        def refused(payload):
            (self.docs/'a.md').write_text('Changed version');raise ValueError(CAPACITY)
        self.worker.answer=refused
        with self.assertRaisesRegex(ValueError,'Enrolled version unavailable'):self.ask(s)
        self.assertEqual(self.worker.calls,0);self.assertEqual(s.last_attempt()['status'],'failed')

    def test_failure_after_model_attempt_cannot_trigger_fallback(self):
        self.enroll('ZP21 livraison lundi.');s=AdaptiveContextSession(self.adapter,self.worker)
        def charged_error(payload):
            self.worker._attempts.append(dict(stage='answer'));raise ValueError(CAPACITY)
        self.worker.answer=charged_error
        with self.assertRaisesRegex(ValueError,'Prompt exceeds'):self.ask(s)
        self.assertEqual(s.last_attempt()['routes'],['full'])
        self.assertEqual(s.last_attempt()['model_calls'],1)

    def test_still_oversized_stops_after_one_fallback(self):
        self.enroll('ZP21 livraison '+'x'*300);s=AdaptiveContextSession(self.adapter,self.worker)
        with self.assertRaisesRegex(ValueError,'Prompt exceeds'):self.ask(s)
        self.assertEqual(len(self.payloads),2);self.assertEqual(self.worker.calls,0)
        self.assertEqual(s.last_attempt()['routes'],['full','unique-coverage'])

    def test_invalid_input_and_source_errors_do_not_fallback(self):
        self.enroll('ZP21 livraison lundi.');s=AdaptiveContextSession(self.adapter,self.worker)
        with self.assertRaises(ValueError):s.answer(None,{'day':'Jour'},('a',))
        self.assertEqual(s.last_attempt()['routes'],['full'])
        (self.docs/'a.md').write_text('Changed')
        with self.assertRaisesRegex(ValueError,'Enrolled version unavailable'):self.ask(s)
        self.assertEqual(s.last_attempt()['routes'],['full']);self.assertEqual(self.worker.calls,0)

if __name__=='__main__':unittest.main()
