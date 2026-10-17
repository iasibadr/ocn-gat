import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core.experience_memory import ExperienceMemory


class ExperienceRetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.path=root/'memory.sqlite';self.reservoir=root/'reservoir';self.reservoir.mkdir()
        self.memory=ExperienceMemory.create(self.path,contract_id='test',actions=['a'],capacity=40)
        for n in range(40):self.record(n)

    def record(self,n,**kwargs):
        args=dict(event_id=str(n),context='task',action='a',success=n%2==0,quality=.5,interventions=0,cost=1.)
        args.update(kwargs);return self.memory.record(**args)

    def test_failed_archive_write_does_not_poison_final_name(self):
        with patch('ocn_core.archive_publication.os.fsync',side_effect=OSError('write sync failed')):
            with self.assertRaises(OSError):self.memory.retire(self.reservoir)
        with self.memory.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0],40)
        self.assertEqual(list(self.reservoir.iterdir()),[])
        result=self.memory.retire(self.reservoir)
        self.assertTrue(result['archive'])
        self.assertEqual(len(list(self.reservoir.iterdir())),1)

    def test_archived_events_leave_prediction_unchanged_and_replays_inert(self):
        before=self.memory.estimate('task','a',quality_weight=.5)
        receipt=self.memory.retire(self.reservoir)
        self.assertEqual(receipt['retired'],8)
        archive=json.loads(Path(receipt['archive']).read_text())
        self.assertEqual([r[1] for r in archive['rows']],[str(n) for n in range(8)])
        self.memory=ExperienceMemory(self.path,contract_id='test')
        with self.memory.connect() as db:self.assertEqual(self.memory.metadata(db)['format'],'gat.experience.v2')
        self.assertEqual(self.memory.estimate('task','a',quality_weight=.5),before)
        self.assertFalse(self.record(0))
        with self.assertRaisesRegex(ValueError,'Conflicting retired'):self.record(0,success=False)
        self.assertTrue(self.record(40))
        with self.assertRaisesRegex(ValueError,'retained history'):self.memory.estimate('task','a',window=64)

    def test_failed_archive_acknowledgment_keeps_active_memory(self):
        before=self.memory.estimate('task','a',window=40)
        with patch('ocn_core.model_budget.sync_directory',side_effect=OSError('sync failed')):
            with self.assertRaises(OSError):self.memory.retire(self.reservoir)
        self.assertEqual(self.memory.estimate('task','a',window=40),before)
        self.assertFalse(self.record(0))
        with self.assertRaisesRegex(ValueError,'capacity'):self.record(40)
        # Existing orphan archive is checked and reused on an explicit retry.
        self.assertEqual(self.memory.retire(self.reservoir)['retired'],8)
        self.assertEqual(len(list(self.reservoir.iterdir())),1)

    def test_partial_batch_is_bounded_and_cannot_enlarge_history(self):
        self.assertEqual(self.memory.retire(self.reservoir,limit=3)['retired'],3)
        self.assertEqual(self.memory.retire(self.reservoir,limit=3)['retired'],3)
        self.assertEqual(self.memory.retire(self.reservoir,limit=3)['retired'],2)
        self.assertEqual(self.memory.retire(self.reservoir)['retired'],0)
        with self.assertRaisesRegex(ValueError,'expand'):self.memory.retire(self.reservoir,keep_per_pair=64)

    def test_corrupted_orphan_archive_does_not_authorize_retirement(self):
        with patch('ocn_core.model_budget.sync_directory',side_effect=OSError('failed')):
            with self.assertRaises(OSError):self.memory.retire(self.reservoir)
        archive=next(self.reservoir.iterdir());archive.write_text('corrupt')
        with self.assertRaisesRegex(ValueError,'verification'):self.memory.retire(self.reservoir)
        self.assertEqual(self.memory.estimate('task','a',window=40)['observations'],40)


if __name__=='__main__':unittest.main()
