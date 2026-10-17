import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core.model_json import parse_model_json
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_agent import DocumentAgent,LocalDocumentSynthesizer


class ModelJSONTests(unittest.TestCase):
    def test_single_fence_preserves_values_and_provenance(self):
        payload=json.dumps({'value':'é ``` literal','nested':{'x':[1,2]}})
        framed='```json\n'+payload+'\n```'
        plain=parse_model_json(payload);parsed=parse_model_json(framed,allow_json_fence=True)
        self.assertEqual(parsed.value,plain.value)
        self.assertEqual(parsed.payload_sha256,plain.payload_sha256)
        self.assertEqual(parsed.raw_sha256,hashlib.sha256(framed.encode()).hexdigest())
        self.assertNotEqual(parsed.raw_sha256,plain.raw_sha256)
        self.assertEqual(parsed.framing,'single_json_fence')
        with self.assertRaises(ValueError):parse_model_json(framed)

    def test_no_prose_multiple_blocks_or_field_repairs(self):
        for raw in ('Here: {}','{} trailing','```python\n{}\n```','```json\n{}\n```\n```json\n{}\n```',
                    '```json\n{}','{"value":1,}','[1]','null'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_model_json(raw,allow_json_fence=True)

    def test_ambiguous_and_nonfinite_json_rejected(self):
        for raw in ('{"x":1,"x":2}','{"nested":{"a":1,"a":2}}','{"x":NaN}',
                    '{"x":Infinity}','{"x":1e309}'):
            with self.assertRaises(ValueError):parse_model_json(raw)
        with self.assertRaises(ValueError):parse_model_json('{"x":'+('['*40)+'0'+(']'*40)+'}')
        with self.assertRaises(ValueError):parse_model_json('{"x":"é"}',max_bytes=9)
        with self.assertRaises(ValueError):parse_model_json('{}',allow_json_fence=1)

    def test_optional_local_framing_does_not_bypass_document_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docs=root/'docs';docs.mkdir();(docs/'a.md').write_text('Delivery Friday.')
            adapter=DocumentAdapter(docs,root/'bindings.json');adapter.bind('a','a.md')
            source=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')])
            def endpoint(*args,**kw):
                text='```json\n'+json.dumps(source)+'\n```'
                return io.BytesIO(json.dumps(dict(done=True,done_reason='stop',message=dict(content=text),prompt_eval_count=50,eval_count=25)).encode())
            with patch('ocn_core.document_agent.require_model',return_value={'digest':'a'*64}),patch('ocn_core.document_agent.urllib.request.urlopen',side_effect=endpoint) as calls:
                strict=DocumentAgent(adapter,LocalDocumentSynthesizer())
                with self.assertRaises(ValueError):strict.answer('When?',('a',))
                flexible=DocumentAgent(adapter,LocalDocumentSynthesizer(allow_json_fence=True))
                answer=flexible.answer('When?',('a',))
                self.assertEqual(answer['answer'],'Friday')
                self.assertEqual(answer['usage']['response_framing'],'single_json_fence')
                source['citations'][0]['quote']='Monday'
                with self.assertRaises(ValueError):flexible.answer('When?',('a',))
                self.assertEqual(calls.call_count,3)  # No repair inference or hidden retry.

if __name__=='__main__':unittest.main()
