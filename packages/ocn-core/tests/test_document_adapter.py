import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core.document_adapter import DocumentAdapter

class DocumentAdapterTests(unittest.TestCase):
    def fixture(self,root,**kwargs):
        h=root/'h';h.mkdir();(h/'source.md').write_text('Delivery: Friday.',encoding='utf-8')
        adapter=DocumentAdapter(h,root/'documents.json',**kwargs);adapter.bind('delivery','source.md')
        return h,adapter
    def test_move_replacement_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            (h/'nested').mkdir();(h/'source.md').rename(h/'nested'/'new.md');(h/'source.md').write_text('Delivery: Monday.')
            result=a.read('delivery')
            self.assertEqual(result.text,'Delivery: Friday.');self.assertEqual(result.relocated_from,'source.md')
            restored=DocumentAdapter(h,root/'documents.json');again=restored.read('delivery')
            self.assertEqual(again.path,'nested/new.md');self.assertIsNone(again.relocated_from)
            self.assertEqual(again.entries_scanned,0)
    def test_changed_content_does_not_silently_replace_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root);before=a.state.read_bytes()
            (h/'source.md').write_text('Delivery: Monday.')
            with self.assertRaises(ValueError):a.read('delivery')
            self.assertEqual(a.state.read_bytes(),before)
            with self.assertRaises(ValueError):a.bind('delivery','source.md')
    def test_ambiguous_move_leaves_binding_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root);before=a.state.read_bytes()
            (h/'source.md').rename(h/'a.md');(h/'b.md').write_text((h/'a.md').read_text())
            with self.assertRaises(ValueError):a.read('delivery')
            self.assertEqual(a.state.read_bytes(),before)
    def test_escape_and_symlink_are_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root);(root/'secret.txt').write_text('secret')
            (h/'link.txt').symlink_to(root/'secret.txt')
            for path in ('../secret.txt','link.txt','/absolute.txt'):
                with self.assertRaises(ValueError):a.bind('forbidden',path)
    def test_parent_symlink_swap_between_validation_and_open_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            folder=h/'nested';folder.mkdir();(folder/'item.md').write_text('inside')
            outside=root/'outside';outside.mkdir();(outside/'item.md').write_text('outside')
            before=a.state.read_bytes();original=os.open;swapped=[]
            def racing_open(path,flags,*args,**kwargs):
                if path=='nested' and not swapped:
                    folder.rename(h/'saved');folder.symlink_to(outside,target_is_directory=True);swapped.append(True)
                return original(path,flags,*args,**kwargs)
            with patch('ocn_core.document_adapter.os.open',side_effect=racing_open):
                with self.assertRaises(OSError):a.bind('candidate','nested/item.md')
            self.assertTrue(swapped);self.assertEqual(a.state.read_bytes(),before)

    def test_open_parent_descriptor_cannot_be_redirected_by_later_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            folder=h/'nested';folder.mkdir();(folder/'item.md').write_text('inside')
            outside=root/'outside';outside.mkdir();(outside/'item.md').write_text('outside')
            original=os.open;swapped=[]
            def racing_open(path,flags,*args,**kwargs):
                if path=='item.md' and not swapped:
                    folder.rename(h/'saved');folder.symlink_to(outside,target_is_directory=True);swapped.append(True)
                return original(path,flags,*args,**kwargs)
            with patch('ocn_core.document_adapter.os.open',side_effect=racing_open):
                digest,text=a._read('nested/item.md',{'bytes':0})
            self.assertTrue(swapped);self.assertEqual(text,'inside')
            # A later read observes the hostile replacement and refuses it.
            with self.assertRaisesRegex(ValueError,'symlinks'):a._read('nested/item.md',{'bytes':0})

    def test_scan_and_byte_budgets_do_not_promote_partial_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root,max_entries=1);before=a.state.read_bytes()
            (h/'source.md').rename(h/'moved.md');(h/'other.txt').write_text('x')
            with self.assertRaises(ValueError):a.read('delivery')
            self.assertEqual(a.state.read_bytes(),before)
            b=DocumentAdapter(h,root/'other.json',max_bytes=2)
            with self.assertRaises(ValueError):b.bind('x','moved.md')
            self.assertFalse(b.state.exists())
    def test_fifo_cannot_block_document_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root);os.mkfifo(h/'pipe.txt')
            with self.assertRaises(ValueError):a.bind('pipe','pipe.txt')

    def test_unknown_document_and_tampered_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            with self.assertRaises(ValueError):a.read('unknown')
            payload=json.loads(a.state.read_text());payload['documents']['delivery']['path']='../outside.txt'
            a.state.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):a.read('delivery')

    def test_length_hint_saves_reads_without_accepting_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            size=(h/'source.md').stat().st_size
            (h/'source.md').rename(h/'moved.md')
            (h/'large.md').write_text('x'*4096)
            result=a.read('delivery',discovery_bytes=size)
            self.assertEqual(result.bytes_read,2*size)
            (h/'moved.md').rename(h/'again.md')
            (h/'duplicate.md').write_text(result.text)
            before=a.state.read_bytes()
            with self.assertRaisesRegex(ValueError,'Ambiguous'):
                a.read('delivery',discovery_bytes=size)
            self.assertEqual(a.state.read_bytes(),before)

    def test_wrong_hint_fails_closed_without_changing_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            # A hint never suppresses verification of a currently bound path.
            self.assertEqual(a.read('delivery',discovery_bytes=0).text,'Delivery: Friday.')
            (h/'source.md').rename(h/'moved.md');before=a.state.read_bytes()
            with self.assertRaises(ValueError):a.read('delivery',discovery_bytes=0)
            self.assertEqual(a.state.read_bytes(),before)
            for invalid in (True,-1,1.2,'4'):
                with self.assertRaises(ValueError):a.read('delivery',discovery_bytes=invalid)

if __name__=='__main__':unittest.main()
