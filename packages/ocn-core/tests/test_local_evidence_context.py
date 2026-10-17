import copy,io,json,unittest
from unittest.mock import patch
from ocn_core.local_evidence_context import LocalEvidenceContextWorker

class LocalTests(unittest.TestCase):
    def setUp(self):
        self.request=dict(question='Date?',fields={'date':'Which date?'},paragraphs=[dict(id='s0:p0',document_id='d',start=0,end=7,text='Friday.')])
        self.model=patch('ocn_core.local_evidence_context.require_model',return_value={'digest':'fixed'}).start();self.addCleanup(patch.stopall)
    def response(self,content,**kwargs):
        return io.BytesIO(json.dumps(dict(done=True,done_reason='stop',prompt_eval_count=100,eval_count=20,message=dict(content=content),**kwargs)).encode())
    def test_two_callbacks_share_budget_and_pin_revision(self):
        w=LocalEvidenceContextWorker('installed',max_calls=2);seen=[]
        def http(req,timeout):
            seen.append(json.loads(req.data));self.assertEqual(req.full_url,'http://127.0.0.1:11434/api/chat');self.assertEqual(timeout,60)
            return self.response('{"date":["s0:p0"]}' if len(seen)==1 else '{"date":{"status":"supported","answer":"Friday","references":["s0:p0"]}}')
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',http):
            self.assertEqual(w.select(self.request),{'date':['s0:p0']});w.answer(self.request)
            with self.assertRaises(RuntimeError):w.answer(self.request)
        self.assertEqual(w.calls,2);self.assertEqual([x['stage'] for x in w.attempts()],['select','answer'])
        self.assertTrue(all(x['completed'] for x in w.attempts()));self.assertEqual(seen[0]['options']['num_predict'],768)
        self.assertTrue(w.revision().startswith('local-evidence-context:'))
    def test_transport_failure_charged_with_unknown_usage(self):
        w=LocalEvidenceContextWorker('installed',max_calls=1)
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):w.select(self.request)
        self.assertEqual(w.calls,1);self.assertIsNone(w.attempts()[0]['input_tokens'])
        self.assertFalse(w.attempts()[0]['completed'])
    def test_parse_failure_keeps_known_usage(self):
        w=LocalEvidenceContextWorker('installed')
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',return_value=self.response('not json')):
            with self.assertRaises(ValueError):w.answer(self.request)
        self.assertEqual(w.attempts()[0]['input_tokens'],100);self.assertFalse(w.attempts()[0]['completed'])
    def test_invalid_input_and_model_change_prevent_chat(self):
        w=LocalEvidenceContextWorker('installed')
        bad=copy.deepcopy(self.request);bad['paragraphs']*=2
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen') as http:
            with self.assertRaises(ValueError):w.select(bad)
            self.model.return_value={'digest':'changed'}
            with self.assertRaises(ValueError):w.answer(self.request)
            http.assert_not_called()
        self.assertEqual(w.calls,0)
    def test_empty_context_and_attempt_copies(self):
        w=LocalEvidenceContextWorker('installed');request=dict(self.request,paragraphs=[])
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',return_value=self.response('{"date":{"status":"unknown","answer":null,"references":[]}}')) as http:
            w.answer(request)
            schema=json.loads(http.call_args.args[0].data)['format']
            self.assertEqual(schema['properties']['date']['properties']['references']['maxItems'],0)
        copy_attempts=w.attempts();copy_attempts[0]['input_tokens']=999
        self.assertEqual(w.attempts()[0]['input_tokens'],100)
    def test_reentrance_refused_and_no_semantic_claim(self):
        w=LocalEvidenceContextWorker('installed')
        def http(*args,**kwargs):
            with self.assertRaises(RuntimeError):w.answer(self.request)
            return self.response('{"date":{"status":"supported","answer":"Monday","references":["s0:p0"]}}')
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',http):result=w.answer(self.request)
        self.assertEqual(result['date']['answer'],'Monday');self.assertEqual(w.calls,1)
        self.assertNotIn('semantic_verification',w.attempts()[0])
    def test_context_and_truncated_response(self):
        w=LocalEvidenceContextWorker('installed');bad=copy.deepcopy(self.request)
        bad['paragraphs'][0].update(text='x'*20000,end=20000)
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen') as http:
            with self.assertRaises(ValueError):w.answer(bad)
            http.assert_not_called()
        body=dict(done=True,done_reason='length',prompt_eval_count=100,eval_count=768,message=dict(content='{}'))
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(body).encode())):
            with self.assertRaises(ValueError):w.answer(self.request)
        self.assertEqual(w.calls,1);self.assertEqual(w.attempts()[0]['output_tokens'],768)

    def test_preflight_is_pure_and_matches_wire_capacity(self):
        from ocn_core.context_budget import select_context
        w=LocalEvidenceContextWorker('installed',max_calls=1)
        before=copy.deepcopy(self.request)
        with patch('ocn_core.local_evidence_context.require_model',side_effect=AssertionError('network inventory forbidden')),patch('ocn_core.local_evidence_context.urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            plan=w.context_plan(self.request)
        self.assertEqual(w.calls,0);self.assertEqual(self.request,before)
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen',return_value=self.response('{"date":{"status":"unknown","answer":null,"references":[]}}')) as http:
            w.answer(self.request)
        payload=json.loads(http.call_args.args[0].data)
        self.assertEqual(plan,select_context(payload['messages'],payload['options']['num_predict']))
        self.assertEqual(plan['requested_window'],payload['options']['num_ctx'])
        # Preflight measures capacity, including after the inference budget ends.
        self.assertEqual(w.context_plan(self.request),plan)
        self.assertEqual(w.calls,1)

    def test_preflight_refuses_oversize_and_invalid_without_call(self):
        w=LocalEvidenceContextWorker('installed')
        bad=copy.deepcopy(self.request)
        bad['paragraphs'][0].update(text='x'*20000,end=20000)
        with patch('ocn_core.local_evidence_context.urllib.request.urlopen') as http:
            with self.assertRaisesRegex(ValueError,'conservative context'):w.context_plan(bad)
            with self.assertRaises(ValueError):w.context_plan(dict(self.request,unexpected=True))
            http.assert_not_called()
        self.assertEqual(w.calls,0)

if __name__=='__main__':unittest.main()
