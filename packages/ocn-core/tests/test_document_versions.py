from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from ocn_core.document_adapter import DocumentAdapter

class DocumentVersionTests(unittest.TestCase):
    def fixture(self,root):
        h=root/'h';h.mkdir();(h/'old.md').write_text('Delivery Friday.')
        a=DocumentAdapter(h,root/'state.json');old=a.bind('plan','old.md')
        return h,a,old
    def digest(self,text):return hashlib.sha256(text.encode()).hexdigest()
    def test_authorized_move_and_update_persists_and_invalidates_old_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a,old=self.fixture(root);(h/'old.md').unlink();(h/'new.md').write_text('Delivery Monday.')
            new=a.accept_version('plan','new.md',expected_current_sha256=old.sha256,expected_new_sha256=self.digest('Delivery Monday.'))
            self.assertEqual(new.text,'Delivery Monday.')
            restored=DocumentAdapter(h,a.state)
            self.assertEqual(restored.read('plan').sha256,new.sha256)
            self.assertEqual(restored.validate_reference(new,'Monday')['path'],'new.md')
            with self.assertRaises(ValueError):restored.validate_reference(old,'Friday')
            self.assertEqual(old.text,'Delivery Friday.') # Prior observation remains immutable.
    def test_stale_authorization_cannot_undo_newer_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a,old=self.fixture(root);(h/'new.md').write_text('Delivery Monday.')
            a.accept_version('plan','new.md',expected_current_sha256=old.sha256,expected_new_sha256=self.digest('Delivery Monday.'))
            before=a.state.read_bytes()
            with self.assertRaises(ValueError):a.accept_version('plan','old.md',expected_current_sha256=old.sha256,expected_new_sha256=old.sha256)
            self.assertEqual(a.state.read_bytes(),before)
    def test_unexpected_candidate_or_unknown_id_does_not_modify_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a,old=self.fixture(root);before=a.state.read_bytes()
            for ident in ('plan','unknown'):
                with self.assertRaises(ValueError):a.accept_version(ident,'old.md',expected_current_sha256=old.sha256,expected_new_sha256='0'*64)
                self.assertEqual(a.state.read_bytes(),before)
    def test_changes_during_synthesis_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a,old=self.fixture(root)
            a.validate_reference(old,'Friday')
            (h/'old.md').write_text('Delivery Monday.')
            with self.assertRaises(ValueError):a.validate_reference(old,'Friday')
    def test_quote_membership_does_not_certify_claim_and_rejects_forged_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a,old=self.fixture(root)
            with self.assertRaises(ValueError):a.validate_reference(old,'Monday')
            with self.assertRaises(ValueError):a.validate_reference(replace(old,text='Delivery Monday.'),'Monday')
            self.assertEqual(a.validate_reference(old,'Friday')['sha256'],old.sha256)
    def test_reference_follows_verified_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a,old=self.fixture(root);(h/'old.md').rename(h/'moved.md');a.read('plan')
            self.assertEqual(a.validate_reference(old,'Friday')['path'],'moved.md')

if __name__=='__main__':unittest.main()
