import copy
import io
import json
import unittest
from unittest.mock import patch
from ocn_core.context_budget import select_context,check_context_usage
from ocn_core.document_agent import LocalDocumentSynthesizer
from ocn_core.designer import LocalDocumentDesigner


class ContextTests(unittest.TestCase):
    def messages(self,text):return [dict(role='user',content=text)]

    def test_smallest_window_and_no_input_change(self):
        for size,expected in ((2048,4096),(2049,8192),(6144,8192),(6145,16384),(14336,16384)):
            messages=self.messages('x'*size);before=copy.deepcopy(messages)
            self.assertEqual(select_context(messages)['requested_window'],expected)
            self.assertEqual(messages,before)
        with self.assertRaises(ValueError):select_context(self.messages('x'*14337))

    def test_unicode_count_is_bytes(self):
        self.assertEqual(select_context(self.messages('é'*1024))['requested_window'],4096)
        self.assertEqual(select_context(self.messages('é'*1025))['requested_window'],8192)

    def test_usage_overflow_or_invalid_count_rejected(self):
        plan=select_context(self.messages('small'))
        check_context_usage(2048,plan)
        for count in (2049,True,-1,None,'10'):
            with self.assertRaises(ValueError):check_context_usage(count,plan)

    def test_synthesis_payload_preserves_documents_and_reports_context(self):
        documents=[dict(document_id='d',sha256='0'*64,text='Delivery Friday.')]
        answer=dict(answer='Friday.',abstain=False,citations=[dict(document_id='d',quote='Delivery Friday.')])
        raw=json.dumps(dict(done=True,done_reason='stop',prompt_eval_count=200,eval_count=30,message=dict(content=json.dumps(answer)))).encode()
        with patch('ocn_core.document_agent.require_model',return_value={'digest':'test'}),patch('ocn_core.document_agent.urllib.request.urlopen',return_value=io.BytesIO(raw)) as call:
            result=LocalDocumentSynthesizer('fixture')('When?',documents)
        payload=json.loads(call.call_args.args[0].data)
        self.assertEqual(payload['options']['num_ctx'],4096)
        self.assertEqual(json.loads(payload['messages'][1]['content'])['documents'],documents)
        self.assertEqual(result['usage']['context_request']['requested_window'],4096)

    def test_designer_uses_same_policy(self):
        choice=dict(documents=['d'],rationale='Relevant',abstain=False)
        raw=json.dumps(dict(done=True,done_reason='stop',prompt_eval_count=150,eval_count=30,message=dict(content=json.dumps(choice)))).encode()
        with patch('ocn_core.designer.require_model',return_value={'digest':'test'}),patch('ocn_core.designer.urllib.request.urlopen',return_value=io.BytesIO(raw)) as call:
            result=LocalDocumentDesigner('fixture')('Read',[dict(document_id='d',path='d.md',description='Document')])
        self.assertEqual(json.loads(call.call_args.args[0].data)['options']['num_ctx'],4096)
        self.assertEqual(result['usage']['context_request']['requested_window'],4096)

    def test_oversize_rejected_before_inference(self):
        with patch('ocn_core.document_agent.require_model',return_value={'digest':'test'}),patch('ocn_core.document_agent.urllib.request.urlopen') as call:
            with self.assertRaises(ValueError):
                LocalDocumentSynthesizer('fixture')('Read',[dict(document_id='d',text='x'*16000)])
            call.assert_not_called()

if __name__=='__main__':unittest.main()
