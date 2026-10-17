import hashlib
import io
import json
import unittest
from unittest.mock import patch
from ocn_core.local_temporal_extractor import LocalTemporalExtractor

class LocalTemporalExtractorTests(unittest.TestCase):
    def request(self):
        text='On 2026-01-01, the shoes are in the drawer.'
        return dict(subject='shoes',predicate='location',documents=[dict(source_id='a',text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),observed_at='2026-01-01T00:00:00+00:00')])
    def response(self,**updates):
        result=dict(done=True,done_reason='stop',message=dict(content='```json\n{"statements":[]}\n```'),prompt_eval_count=100,eval_count=10)
        result.update(updates);return io.BytesIO(json.dumps(result).encode())
    def test_one_call_framing_and_observable_usage(self):
        with patch('ocn_core.local_temporal_extractor.require_model',return_value={'digest':'a'*64}),patch('ocn_core.local_temporal_extractor.urllib.request.urlopen',return_value=self.response()) as call:
            result=LocalTemporalExtractor(allow_json_fence=True)(self.request())
            self.assertEqual(result['extraction'],{'statements':[]})
            self.assertEqual(result['usage']['model_calls'],1)
            self.assertEqual(result['usage']['response_framing'],'single_json_fence')
            self.assertEqual(call.call_count,1)
            body=json.loads(call.call_args.args[0].data)
            self.assertEqual(json.loads(body['messages'][1]['content']),self.request())
    def test_bad_snapshot_or_budget_prevents_inference(self):
        with patch('ocn_core.local_temporal_extractor.urllib.request.urlopen') as call:
            request=self.request();request['documents'][0]['sha256']='0'*64
            with self.assertRaises(ValueError):LocalTemporalExtractor()(request)
            request=self.request();request['predicate']='ownership'
            with self.assertRaises(ValueError):LocalTemporalExtractor()(request)
            request=self.request();doc=request['documents'][0];doc['text']='x'*32768;doc['sha256']=hashlib.sha256(doc['text'].encode()).hexdigest()
            with self.assertRaises(ValueError):LocalTemporalExtractor()(request)
            call.assert_not_called()
    def test_truncation_context_overflow_changed_model_and_strict_framing_reject(self):
        for response in (self.response(done_reason='length'),self.response(prompt_eval_count=999999),self.response()):
            with patch('ocn_core.local_temporal_extractor.require_model',return_value={'digest':'a'*64}),patch('ocn_core.local_temporal_extractor.urllib.request.urlopen',return_value=response) as call:
                with self.assertRaises(ValueError):LocalTemporalExtractor()(self.request())
                self.assertEqual(call.call_count,1)
        with patch('ocn_core.local_temporal_extractor.require_model',side_effect=[{'digest':'a'*64},{'digest':'b'*64}]),patch('ocn_core.local_temporal_extractor.urllib.request.urlopen',return_value=self.response()):
            with self.assertRaisesRegex(ValueError,'Model changed'):LocalTemporalExtractor(allow_json_fence=True)(self.request())

if __name__=='__main__':unittest.main()
