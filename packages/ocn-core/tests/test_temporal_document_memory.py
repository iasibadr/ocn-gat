import hashlib
from pathlib import Path
import tempfile
import unittest
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.temporal_document_memory import capture,query

D1='2026-01-01T00:00:00+00:00';D2='2026-01-02T00:00:00+00:00'

class TemporalDocumentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.text='On 2026-01-01, the shoes are in the drawer.'
        (self.docs/'a.md').write_text(self.text)
        self.adapter=DocumentAdapter(self.docs,self.root/'bindings.json');self.adapter.bind('a','a.md')
        self.state=self.root/'memory.json'
        self.extraction=dict(statements=[dict(source_id='a',value='drawer',quote=self.text,polarity='affirmed',date_quote='2026-01-01')])
    def capture(self):
        return capture(self.adapter,self.state,self.extraction,{'a':D1},subject='shoes',predicate='location',expected_source_sha256={i:v['sha256'] for i,v in self.adapter.bindings().items()})['memory_sha256']
    def query(self,digest):
        return query(self.adapter,self.state,expected_sha256=digest,known_at=D2,effective_at=D2)
    def test_reopen_and_relocate_preserves_candidate_not_truth(self):
        digest=self.capture();before=self.state.read_bytes()
        (self.docs/'a.md').rename(self.docs/'moved.md')
        self.adapter=DocumentAdapter(self.docs,self.root/'bindings.json')
        result=self.query(digest)
        self.assertEqual(result['candidate_value'],'drawer')
        self.assertEqual(result['provenance'][0]['path'],'moved.md')
        self.assertTrue(result['candidate_only']);self.assertFalse(result['semantic_verification'])
        self.assertNotIn('value',result);self.assertEqual(self.state.read_bytes(),before)
    def test_changed_or_deleted_source_never_reuses_cached_answer(self):
        digest=self.capture()
        (self.docs/'a.md').write_text('Now the shoes are in the locker.')
        result=self.query(digest)
        self.assertEqual(result['status'],'unresolved_provenance');self.assertIsNone(result['candidate_value'])
        (self.docs/'a.md').unlink()
        self.assertEqual(self.query(digest)['status'],'unresolved_provenance')
    def test_authorized_upgrade_still_invalidates_old_candidate(self):
        digest=self.capture();old=self.adapter.bindings()['a']['sha256']
        text='On 2026-01-02, the shoes are in the locker.';(self.docs/'a.md').write_text(text)
        self.adapter.accept_version('a','a.md',expected_current_sha256=old,expected_new_sha256=hashlib.sha256(text.encode()).hexdigest())
        result=self.query(digest)
        self.assertEqual(result['unavailable'][0]['reason'],'version_changed')
        self.assertIsNone(result['candidate_value'])
    def test_immutable_batch_integrity_and_invalid_extraction(self):
        digest=self.capture()
        with self.assertRaises(FileExistsError):self.capture()
        self.state.write_bytes(self.state.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.query(digest)
        self.state.unlink();self.extraction['statements'][0]['quote']='invented'
        with self.assertRaises(ValueError):self.capture()
        self.assertFalse(self.state.exists())
    def test_even_source_omitted_by_extractor_must_remain_available(self):
        (self.docs/'b.md').write_text('No statement selected by the model.')
        self.adapter.bind('b','b.md')
        digest=capture(self.adapter,self.state,self.extraction,{'a':D1,'b':D2},subject='shoes',predicate='location',expected_source_sha256={i:v['sha256'] for i,v in self.adapter.bindings().items()})['memory_sha256']
        (self.docs/'b.md').unlink()
        result=self.query(digest)
        self.assertEqual(result['status'],'unresolved_provenance')
        self.assertIsNone(result['candidate_value'])

    def test_same_quote_in_new_version_cannot_rebind_old_interpretation(self):
        old=self.adapter.read('a').sha256
        text=self.text+' Later correction: the shoes were moved elsewhere.'
        (self.docs/'a.md').write_text(text)
        self.adapter.accept_version('a','a.md',expected_current_sha256=old,
            expected_new_sha256=hashlib.sha256(text.encode()).hexdigest())
        with self.assertRaisesRegex(ValueError,'interpreted snapshot'):
            capture(self.adapter,self.state,self.extraction,{'a':D1},subject='shoes',predicate='location',expected_source_sha256={'a':old})
        self.assertFalse(self.state.exists())

    def test_semantically_wrong_but_anchored_candidate_is_not_certified(self):
        self.extraction['statements'][0]['value']='shoes'
        digest=self.capture();result=self.query(digest)
        self.assertEqual(result['candidate_value'],'shoes')
        self.assertFalse(result['semantic_verification']);self.assertTrue(result['candidate_only'])

if __name__=='__main__':unittest.main()
