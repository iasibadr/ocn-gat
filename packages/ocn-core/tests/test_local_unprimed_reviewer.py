import io,json,unittest
from unittest.mock import patch
from ocn_core.local_unprimed_reviewer import LocalUnprimedReviewer
from ocn_core.unprimed_verifier import UnprimedVerifier,evidence_catalog

class LocalReviewerTests(unittest.TestCase):
 def request(self):return {'question':'Confirmed city?','document_id':'a','record':{'city':'Berne'},'evidence_catalog':evidence_catalog({'city':'Berne'})}
 def response(self,content=None,**overrides):
  b={'done':True,'done_reason':'stop','prompt_eval_count':100,'eval_count':20,'message':{'content':content or '{"status":"value","reference":"e0","reason":"confirmed"}'}};b.update(overrides)
  return io.BytesIO(json.dumps(b).encode())
 def model_patch(self,**kwargs):return patch('ocn_core.local_unprimed_reviewer.require_model',**kwargs)
 def http_patch(self,**kwargs):return patch('ocn_core.local_unprimed_reviewer.urllib.request.urlopen',**kwargs)
 def test_composition_pinning_and_usage_without_candidate(self):
  with self.model_patch(return_value={'digest':'a'*64}),self.http_patch(return_value=self.response()) as http:
   r=LocalUnprimedReviewer('fixture',max_calls=1);v=UnprimedVerifier('Confirmed city?',r,reviewer_id=r.reviewer_id)
   self.assertTrue(v.verify({'city':'Berne'},'a','Berne'))
   request=http.call_args.args[0];payload=json.loads(request.data)
   self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/chat')
   self.assertNotIn('candidate',json.loads(payload['messages'][1]['content']))
   self.assertEqual(r.last_usage['input_tokens'],100);self.assertTrue(r.last_usage['completed'])
   copied=r.last_usage;copied['input_tokens']=0;self.assertEqual(r.last_usage['input_tokens'],100)
   with self.assertRaisesRegex(RuntimeError,'budget'):r(self.request())
   self.assertEqual(http.call_count,1)
 def test_model_change_blocks_chat(self):
  with self.model_patch(side_effect=[{'digest':'a'*64},{'digest':'b'*64}]),self.http_patch() as http:
   r=LocalUnprimedReviewer('fixture')
   with self.assertRaisesRegex(ValueError,'changed'):r(self.request())
   self.assertEqual(r.calls,0);http.assert_not_called()
 def test_invalid_input_and_forged_catalog_block_chat(self):
  with self.model_patch(return_value={'digest':'a'*64}),self.http_patch() as http:
   r=LocalUnprimedReviewer('fixture')
   bad=self.request();bad['candidate']='Berne'
   with self.assertRaises(ValueError):r(bad)
   bad=self.request();bad['evidence_catalog'][0]['value']='Berlin'
   with self.assertRaises(ValueError):r(bad)
   http.assert_not_called()
 def test_malformed_or_truncated_response_still_counts_tokens(self):
  for response in (self.response('not JSON'),self.response(done_reason='length'),self.response(message=[])):
   with self.model_patch(return_value={'digest':'a'*64}),self.http_patch(return_value=response):
    r=LocalUnprimedReviewer('fixture')
    with self.assertRaises(ValueError):r(self.request())
    self.assertEqual(r.calls,1);self.assertEqual(r.last_usage['output_tokens'],20);self.assertFalse(r.last_usage['completed'])
 def test_transport_failure_is_charged_with_unknown_usage(self):
  with self.model_patch(return_value={'digest':'a'*64}),self.http_patch(side_effect=TimeoutError('timeout')):
   r=LocalUnprimedReviewer('fixture')
   with self.assertRaises(TimeoutError):r(self.request())
   self.assertEqual(r.calls,1);self.assertIsNone(r.last_usage['input_tokens'])
 def test_fenced_response_and_reentrance(self):
  with self.model_patch(return_value={'digest':'a'*64}):
   r=LocalUnprimedReviewer('fixture')
   def http(*args,**kwargs):
    with self.assertRaisesRegex(RuntimeError,'busy'):r(self.request())
    return self.response('```json\n{"status":"absent","reference":null,"reason":"unknown"}\n```')
   with self.http_patch(side_effect=http):self.assertEqual(r(self.request())['status'],'absent')
   self.assertEqual(r.last_usage['framing'],'single_json_fence');self.assertEqual(r.calls,1)

if __name__=='__main__':unittest.main()
