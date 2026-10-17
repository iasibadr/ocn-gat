import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.temporal_document_memory import query
from ocn_core.temporal_extraction_session import extract_and_capture

DATE='2026-01-01T00:00:00+00:00'

class TemporalExtractionSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.docs=root/'docs';self.docs.mkdir();self.state=root/'memory.json'
        self.text='On 2026-01-01, the shoes are in the drawer.'
        (self.docs/'a.md').write_text(self.text)
        self.adapter=DocumentAdapter(self.docs,root/'binding.json');self.adapter.bind('a','a.md')
        self.response=dict(extraction=dict(statements=[dict(source_id='a',value='drawer',quote=self.text,
            polarity='affirmed',date_quote='2026-01-01')]),usage=dict(model_calls=0))
    def run_extraction(self,fn,**kwargs):
        return extract_and_capture(self.adapter,self.state,fn,{'a':DATE},subject='shoes',predicate='location',**kwargs)
    def test_movement_during_extraction_and_repeated_query_no_extra_call(self):
        def extraction(request):
            self.assertEqual(request['documents'][0]['text'],self.text)
            (self.docs/'a.md').rename(self.docs/'moved.md')
            return self.response
        fn=Mock(side_effect=extraction);receipt=self.run_extraction(fn)
        for _ in range(3):
            result=query(self.adapter,self.state,expected_sha256=receipt['memory_sha256'],known_at=DATE,effective_at=DATE)
            self.assertEqual(result['candidate_value'],'drawer')
            self.assertFalse(result['semantic_verification'])
        self.assertEqual(fn.call_count,1)
    def test_mutating_request_cannot_authorize_source_change(self):
        def extraction(request):
            old=request['documents'][0]['sha256'];text=self.text+' Correction follows.'
            (self.docs/'a.md').write_text(text);new=hashlib.sha256(text.encode()).hexdigest()
            self.adapter.accept_version('a','a.md',expected_current_sha256=old,expected_new_sha256=new)
            request['documents'][0]['sha256']=new
            return self.response
        fn=Mock(side_effect=extraction)
        with self.assertRaisesRegex(ValueError,'interpreted snapshot'):self.run_extraction(fn)
        self.assertFalse(self.state.exists());self.assertEqual(fn.call_count,1)
    def test_preflight_rejects_budget_and_existing_memory_before_call(self):
        fn=Mock(return_value=self.response)
        with self.assertRaises(ValueError):self.run_extraction(fn,max_context_bytes=1)
        fn.assert_not_called();self.run_extraction(fn)
        with self.assertRaises(FileExistsError):self.run_extraction(fn)
        self.assertEqual(fn.call_count,1)
    def test_invalid_output_never_writes_memory_or_retries(self):
        for output in ({},dict(extraction={'statements':[]},usage=None),dict(extraction={'wrong':[]},usage={})):
            fn=Mock(return_value=output)
            with self.assertRaises(ValueError):self.run_extraction(fn)
            self.assertFalse(self.state.exists());self.assertEqual(fn.call_count,1)

if __name__=='__main__':unittest.main()
