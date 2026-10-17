import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.run_feedback import prepare,save,feedback
from ocn_core.receipt_archive import archive_receipts


class ReceiptArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.docs=root/'docs';self.docs.mkdir();(self.docs/'a.md').write_text('Friday')
        self.instance=root/'instance';self.reservoir=root/'reservoir';self.reservoir.mkdir()
        gat.create(self.instance,self.docs,{'a':'a.md'},'When?',model='fixture')
        _,self.config=gat.load(self.instance);self.directory=prepare(self.instance)
        self.receipts=[save(self.directory,self.config,'When?','fixture',{'document_bytes_read':6,'answer':'Friday'}) for _ in range(3)]
        for receipt in self.receipts[:2]:self.score(receipt['run_id'])

    def score(self,ident):return feedback(self.instance,ident,rubric='test',success=True,quality=1.,interventions=0)

    def test_failed_archive_write_does_not_poison_final_name(self):
        with patch('ocn_core.archive_publication.os.fsync',side_effect=OSError('write sync failed')):
            with self.assertRaises(OSError):archive_receipts(self.instance,self.reservoir)
        self.assertEqual(len(list(self.directory.iterdir())),3)
        self.assertEqual(list(self.reservoir.iterdir()),[])
        result=archive_receipts(self.instance,self.reservoir)
        self.assertTrue(result['archive'])
        self.assertEqual(len(list(self.reservoir.iterdir())),1)

    def test_only_evaluated_receipts_removed_and_bytes_preserved(self):
        original={p.name:p.read_text() for p in self.directory.iterdir()}
        outcome=archive_receipts(self.instance,self.reservoir)
        self.assertEqual(outcome['archived'],2)
        payload=json.loads(Path(outcome['archive']).read_text())
        for row in payload['receipts']:self.assertEqual(row['raw'],original[row['filename']])
        self.assertEqual([p.stem for p in self.directory.iterdir()],[self.receipts[2]['run_id']])
        with self.assertRaises(FileNotFoundError):self.score(self.receipts[0]['run_id'])
        estimate=self.score(self.receipts[2]['run_id'])['estimate']
        self.assertEqual(estimate['observations'],3);self.assertEqual(estimate['expected_return'],1.)

    def test_failed_archive_sync_never_removes_sources(self):
        with patch('ocn_core.receipt_archive.sync_directory',side_effect=OSError('sync failed')):
            with self.assertRaises(OSError):archive_receipts(self.instance,self.reservoir)
        self.assertEqual(len(list(self.directory.iterdir())),3)
        self.assertEqual(archive_receipts(self.instance,self.reservoir)['archived'],2)
        self.assertEqual(len(list(self.reservoir.iterdir())),1)

    def test_corrupt_existing_archive_is_rejected(self):
        with patch('ocn_core.receipt_archive.sync_directory',side_effect=OSError('sync failed')):
            with self.assertRaises(OSError):archive_receipts(self.instance,self.reservoir)
        next(self.reservoir.iterdir()).write_text('corrupted')
        with self.assertRaisesRegex(ValueError,'verification'):archive_receipts(self.instance,self.reservoir)
        self.assertEqual(len(list(self.directory.iterdir())),3)

    def test_partial_removal_still_has_complete_verified_archive(self):
        original=Path.unlink;calls=[]
        def interrupted(path,*args,**kwargs):
            if path.parent==self.directory:
                calls.append(path)
                if len(calls)==2:raise OSError('interrupted removal')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupted):
            with self.assertRaises(OSError):archive_receipts(self.instance,self.reservoir)
        archive=json.loads(next(self.reservoir.iterdir()).read_text())
        self.assertEqual(len(archive['receipts']),2)
        self.assertEqual(len(list(self.directory.iterdir())),2)
        self.assertEqual(archive_receipts(self.instance,self.reservoir)['archived'],1)

    def test_no_implicit_archive_inside_protected_spaces(self):
        for target in (self.instance,self.docs,self.instance.parent):
            with self.assertRaises(ValueError):archive_receipts(self.instance,target)
        self.assertEqual(archive_receipts(self.instance,self.reservoir,limit=1)['archived'],1)

    def test_archival_reopens_capacity_without_erasing_pending_feedback(self):
        for _ in range(253):save(self.directory,self.config,'When?','fixture',{'document_bytes_read':6,'answer':'Friday'})
        with self.assertRaisesRegex(ValueError,'capacity'):prepare(self.instance)
        self.assertEqual(archive_receipts(self.instance,self.reservoir)['archived'],2)
        self.assertEqual(prepare(self.instance),self.directory)
        self.assertEqual(len(list(self.directory.iterdir())),254)


if __name__=='__main__':unittest.main()
