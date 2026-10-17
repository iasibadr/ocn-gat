import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.run_feedback import save, prepare, feedback
from ocn_core.memory_maintenance import configure, status

SOURCE=b'''def build_synthesizer(model):
    def answer(question,documents):
        d=documents[0]
        return dict(response=dict(answer=d['text'],abstain=False,citations=[dict(document_id=d['document_id'],quote=d['text'])]),usage={})
    return answer
'''


class MemoryMaintenanceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);self.docs=root/'docs';self.docs.mkdir()
        (self.docs/'a.md').write_text('Friday')
        self.root=root/'instance';self.reservoir=root/'reservoir';self.reservoir.mkdir()
        gat.create(self.root,self.docs,{'a':'a.md'},'When?',model='fixture',integration=Integration(SOURCE,'build_synthesizer'))

    def seed(self,count,evaluated=True):
        root,config=gat.load(self.root)
        for _ in range(count):
            receipt=save(prepare(root),config,'When?','fixture',dict(document_bytes_read=6))
            if evaluated:feedback(root,receipt['run_id'],rubric='exact',success=True,quality=1.,interventions=0)

    def test_pressure_automatically_archives_and_preserves_learned_choice(self):
        self.seed(160);configure(self.root,self.reservoir,1)
        answer=gat.run(self.root,learned_models=['fixture'],feedback_rubric='exact')
        self.assertEqual(answer['answer'],'Friday')
        self.assertEqual(answer['learned_selection']['candidates'][0]['observations'],32)
        self.assertEqual(answer['learned_selection']['candidates'][0]['expected_return'],1.)
        self.assertEqual(len(list((self.root/'run-receipts').glob('*.json'))),97)
        self.assertEqual(len(list(self.reservoir.iterdir())),2)
        self.assertEqual(status(self.root)['used_cycles'],1)
        self.seed(63)
        with patch('ocn_core.gat.DocumentAgent.answer') as call:
            with self.assertRaisesRegex(RuntimeError,'budget exhausted'):gat.run(self.root,record=True)
            call.assert_not_called()
        with self.assertRaises(FileExistsError):configure(self.root,self.reservoir,5)

    def test_own_archives_fill_environment_then_resume_when_capacity_returns(self):
        # Leave room for the two real archives emitted by one maintenance cycle.
        for i in range(253):(self.reservoir/('occupied-'+str(i))).touch()
        self.seed(160);configure(self.root,self.reservoir,2)
        first=gat.run(self.root,learned_models=['fixture'],feedback_rubric='exact')
        self.assertEqual(first['answer'],'Friday')
        self.assertEqual(len(list(self.reservoir.iterdir())),255)
        archives={p.name:p.read_bytes() for p in self.reservoir.glob('*.json')}
        self.assertEqual(len(archives),2)
        self.seed(63)
        receipts={p.name:p.read_bytes() for p in (self.root/'run-receipts').glob('*.json')}
        # Repeated saturation observations do not consume the remaining cycle.
        for _ in range(2):
            with patch('ocn_core.gat.DocumentAgent.answer') as call:
                with self.assertRaisesRegex(ValueError,'Reservoir file capacity'):
                    gat.run(self.root,record=True)
                call.assert_not_called()
            self.assertEqual(status(self.root)['used_cycles'],1)
            self.assertEqual(receipts,{p.name:p.read_bytes() for p in (self.root/'run-receipts').glob('*.json')})
        # External actor relocates its own two fixture files; OCN deletes nothing.
        for i in range(2):
            (self.reservoir/('occupied-'+str(i))).rename(self.root.parent/('released-'+str(i)))
        result=gat.run(self.root,learned_models=['fixture'],feedback_rubric='exact')
        self.assertEqual(result['answer'],'Friday')
        self.assertEqual(status(self.root)['used_cycles'],2)
        self.assertEqual(result['learned_selection']['candidates'][0]['expected_return'],1.)
        for name,raw in archives.items():self.assertEqual((self.reservoir/name).read_bytes(),raw)

    def test_pause_and_disable_do_not_silently_consume_authority(self):
        self.seed(160);configure(self.root,self.reservoir,1)
        gat.set_paused(self.root, True)
        with self.assertRaisesRegex(RuntimeError,'paused'):gat.run(self.root,record=True)
        self.assertEqual(status(self.root)['used_cycles'],0)
        self.assertFalse(status(self.root,disable=True)['enabled'])
        gat.set_paused(self.root, False)
        gat.run(self.root,record=True)
        self.assertEqual(status(self.root)['used_cycles'],0)
        self.assertEqual(len(list((self.root/'run-receipts').glob('*.json'))),161)
        self.assertEqual(list(self.reservoir.iterdir()),[])

    def test_unevaluated_pressure_is_not_deleted_or_hidden(self):
        self.seed(160,evaluated=False);configure(self.root,self.reservoir,1)
        with patch('ocn_core.gat.DocumentAgent.answer') as call:
            with self.assertRaisesRegex(RuntimeError,'unresolved'):gat.run(self.root,record=True)
            call.assert_not_called()
        self.assertEqual(status(self.root)['used_cycles'],1)
        self.assertEqual(len(list((self.root/'run-receipts').glob('*.json'))),160)
        self.assertEqual(list(self.reservoir.iterdir()),[])

    def test_failed_retirement_consumes_cycle_and_boundary_is_enforced(self):
        with self.assertRaises(ValueError):configure(self.root,self.docs,1)
        self.seed(160);configure(self.root,self.reservoir,1)
        with patch('ocn_core.memory_maintenance.ExperienceMemory.retire',side_effect=OSError('injected')):
            with self.assertRaises(OSError):gat.run(self.root,record=True)
        self.assertEqual(status(self.root)['used_cycles'],1)
        self.assertEqual(len(list((self.root/'run-receipts').glob('*.json'))),160)


if __name__=='__main__':unittest.main()
