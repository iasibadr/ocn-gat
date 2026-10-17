import hashlib,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.live_document_adapter import LiveDocumentAdapter
from ocn_core.evidence_context_session import EvidenceContextSession
from ocn_core.lexical_context import LexicalContextSelector

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
    def adapter(self,**kwargs):
        a=LiveDocumentAdapter(self.docs,self.root/'pins.json',**kwargs);self.addCleanup(a.close);return a
    def enroll(self,a,ident='a',text='LT73 lundi.'):
        (self.docs/(ident+'.md')).write_text(text);a.bind(ident,ident+'.md');a.pin(ident)

    def test_session_continues_with_copies_and_no_persistent_relocation(self):
        a=self.adapter();self.enroll(a);self.enroll(a,'b')
        state=(self.root/'pins.json').read_bytes();calls=[]
        def answer(r):
            calls.append(r)
            return {'day':dict(status='supported',answer='lundi',references=[r['paragraphs'][0]['id']])}
        selector=LexicalContextSelector(True,True)
        s=EvidenceContextSession(a,answer,lambda:'worker:'+selector.revision(),selector=selector,max_callbacks=3)
        ask=lambda:s.answer('Livraison LT73 ?',{'day':'Date'},('a','b'))
        ask();(self.docs/'a.md').rename(self.docs/'first.md');(self.docs/'b.md').rename(self.docs/'second.md')
        r=ask();self.assertTrue(r['session']['selection_cache_hit'])
        self.assertEqual(r['sources']['a']['path'],'first.md');self.assertEqual(r['sources']['b']['path'],'second.md')
        self.assertEqual(len(calls),2);self.assertEqual((self.root/'pins.json').read_bytes(),state)

    def test_unselected_copy_change_during_answer_blocks(self):
        a=self.adapter();self.enroll(a);self.enroll(a,'b')
        def answer(r):
            (self.docs/'b.md').write_text('Tampered')
            return {'day':dict(status='supported',answer='lundi',references=[r['paragraphs'][0]['id']])}
        s=EvidenceContextSession(a,answer,lambda:'v1',selector=LexicalContextSelector(True,True),max_callbacks=2)
        with self.assertRaisesRegex(ValueError,'version changed'):
            s.answer('Livraison LT73 ?',{'day':'Date'},('a','b'))

    def test_reference_validation_uses_live_path(self):
        a=self.adapter();self.enroll(a);doc=a.read('a');(self.docs/'a.md').rename(self.docs/'new.md')
        self.assertEqual(a.validate_reference(doc,'lundi')['path'],'new.md')

    def test_binding_update_requires_explicit_repin(self):
        a=self.adapter();self.enroll(a);old=a.bindings()['a']['sha256']
        (self.docs/'a.md').write_text('LT73 mardi.')
        a.accept_version('a','a.md',expected_current_sha256=old,
            expected_new_sha256=hashlib.sha256((self.docs/'a.md').read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError,'Binding changed'):a.read('a')
        a.unpin('a');a.pin('a');self.assertEqual(a.read('a').text,'LT73 mardi.')

    def test_pin_capacity_and_close(self):
        a=self.adapter(max_pins=1);self.enroll(a)
        (self.docs/'b.md').write_text('Other');a.bind('b','b.md')
        with self.assertRaisesRegex(ValueError,'capacity'):a.pin('b')
        with self.assertRaisesRegex(ValueError,'explicitly pinned'):a.read('b')
        a.close()
        with self.assertRaisesRegex(ValueError,'closed'):a.read('a')

    def test_total_bytes_and_process_scope(self):
        a=self.adapter(max_total_bytes=12);self.enroll(a)
        with self.assertRaisesRegex(ValueError,'budget'):a.read('a')
        with patch('ocn_core.live_document_adapter.os.getpid',return_value=os.getpid()+1):
            with self.assertRaisesRegex(RuntimeError,'process boundaries'):a.read('a')

    def test_root_replacement_during_observation_blocks(self):
        a=self.adapter();self.enroll(a);ref=a._pins['a'][0];original=ref.snapshot
        def swapped():
            result=original();self.docs.rename(self.root/'old');self.docs.mkdir()
            (self.docs/'a.md').write_text('LT73 lundi.');return result
        with patch.object(ref,'snapshot',swapped):
            with self.assertRaisesRegex(ValueError,'Habitat root changed'):a.read('a')

    def test_path_replacement_after_candidate_read_blocks(self):
        a=self.adapter();self.enroll(a);ref=a._pins['a'][0];original=ref._open;count=0
        def swapped(path,**kwargs):
            nonlocal count
            if not kwargs.get('directory'):
                count+=1
                if count==2:
                    (self.docs/'replacement.md').write_text('LT73 lundi.')
                    os.replace(self.docs/'replacement.md',self.docs/'a.md')
            return original(path,**kwargs)
        with patch.object(ref,'_open',swapped):
            with self.assertRaisesRegex(ValueError,'path changed'):a.read('a')

if __name__=='__main__':unittest.main()
