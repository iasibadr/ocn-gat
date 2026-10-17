import hashlib,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.live_document_adapter import _LiveFileReference as PinnedFile

class PinTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.text=b'Le depart VX52 exige un visa.'
        self.digest=hashlib.sha256(self.text).hexdigest()
        (self.docs/'a.md').write_bytes(self.text)
    def pin(self,**kwargs):
        p=PinnedFile(self.docs,'a.md',self.digest,**kwargs);self.addCleanup(p.close);return p

    def test_original_among_four_copies_after_rename(self):
        adapter=DocumentAdapter(self.docs,self.root/'state.json');adapter.bind('a','a.md')
        before=(self.root/'state.json').read_bytes();pin=self.pin()
        for i in range(3):(self.docs/f'copy{i}.md').write_bytes(self.text)
        (self.docs/'archive').mkdir();(self.docs/'a.md').rename(self.docs/'archive/original.md')
        with self.assertRaisesRegex(ValueError,'Ambiguous relocation'):adapter.read('a')
        self.assertEqual(pin.snapshot()['path'],'archive/original.md')
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_directory_rename(self):
        pin=self.pin();(self.docs/'box').mkdir();(self.docs/'a.md').rename(self.docs/'box/a.md')
        (self.docs/'box').rename(self.docs/'newbox')
        self.assertEqual(pin.snapshot()['path'],'newbox/a.md')

    def test_content_change_rejected_despite_old_copy(self):
        pin=self.pin();(self.docs/'copy.md').write_bytes(self.text)
        (self.docs/'a.md').write_bytes(b'Unauthorized change')
        with self.assertRaisesRegex(ValueError,'version changed'):pin.snapshot()

    def test_deleted_file_not_replaced_by_copy(self):
        pin=self.pin();(self.docs/'a.md').unlink();(self.docs/'a.md').write_bytes(self.text)
        with self.assertRaisesRegex(ValueError,'Unlinked'):pin.snapshot()

    def test_move_outside_habitat_rejected(self):
        pin=self.pin();(self.docs/'a.md').rename(self.root/'outside.md')
        (self.docs/'copy.md').write_bytes(self.text)
        with self.assertRaisesRegex(ValueError,'No unique path'):pin.snapshot()

    def test_hardlinks_rejected_before_and_after_pin(self):
        pin=self.pin();os.link(self.docs/'a.md',self.docs/'hard.md')
        with self.assertRaisesRegex(ValueError,'multiply linked'):pin.snapshot()
        with self.assertRaisesRegex(ValueError,'multiply linked'):self.pin()

    def test_no_symlink_traversal(self):
        (self.docs/'alias.md').symlink_to(self.docs/'a.md')
        with self.assertRaises(OSError):PinnedFile(self.docs,'alias.md',self.digest)
        (self.docs/'dir').symlink_to(self.docs,target_is_directory=True)
        with self.assertRaises(OSError):PinnedFile(self.docs,'dir/a.md',self.digest)

    def test_limits(self):
        with self.assertRaises(ValueError):self.pin(max_bytes=1)
        pin=self.pin(max_entries=1);(self.docs/'extra.md').write_text('x')
        with self.assertRaisesRegex(ValueError,'budget exceeded'):pin.snapshot()

    def test_closed_reference_not_reusable(self):
        pin=self.pin();fds=(pin.fd,pin.root_fd);pin.close();pin.close()
        for fd in fds:
            with self.assertRaises(OSError):os.fstat(fd)
        with self.assertRaisesRegex(ValueError,'closed'):pin.snapshot()

    def test_replacement_during_final_open_rejected(self):
        pin=self.pin();original=pin._open
        def swapped(path,**kwargs):
            if not kwargs.get('directory'):
                (self.docs/'replacement.md').write_bytes(self.text)
                os.replace(self.docs/'replacement.md',self.docs/'a.md')
            return original(path,**kwargs)
        with patch.object(pin,'_open',swapped):
            with self.assertRaisesRegex(ValueError,'Candidate changed'):pin.snapshot()

    def test_bad_digest_closes_descriptors(self):
        before=set(os.listdir('/proc/self/fd'))
        with self.assertRaisesRegex(ValueError,'Version differs'):
            PinnedFile(self.docs,'a.md','0'*64)
        self.assertEqual(set(os.listdir('/proc/self/fd')),before)

if __name__=='__main__':unittest.main()
