import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import prepare
from ocn_core.candidate_adoption import adopt,rollback


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        (self.docs/'a.md').write_text('Friday')
        self.old=self.root/'old.py';self.old.write_text('def build_synthesizer(model): return None\n')
        self.new=self.root/'new.py';self.new.write_text('def build_synthesizer(model): return 1\n')
        self.original=prepare(self.old);self.candidate=prepare(self.new);self.instance=self.root/'instance'
        gat.create(self.instance,self.docs,{'a':'a.md'},'When?',integration=self.original,isolated=True)
        self.digest=self.original.descriptor()['sha256']
        self.suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='one',question='When?',
            documents=[dict(document_id='a',text='Friday')],expected={'response':dict(answer='Friday',abstain=False,
            citations=[dict(document_id='a',quote='Friday')])})])
        self.failed=dict(accepted=False,suite_sha256='a'*64)
        self.passed=dict(accepted=True,suite_sha256='a'*64)

    @patch('ocn_core.candidate_adoption.evaluate')
    def test_adopt_preserves_authority_and_pause_then_rolls_back(self,evaluate):
        evaluate.side_effect=[self.failed,self.passed]
        before=gat.status(self.instance);gat.set_paused(self.instance,True)
        report=adopt(self.instance,self.candidate,self.suite,self.digest)
        self.assertTrue(report['adopted'])
        after=gat.status(self.instance)
        for key in ('mission','documents','habitat','model','format'):self.assertEqual(after[key],before[key])
        self.assertEqual(after['lifecycle'],'paused')
        self.assertEqual(after['integration'],self.candidate.descriptor())
        self.new.write_text('changed externally')
        from ocn_core.candidate_adoption import pinned
        self.assertEqual(pinned(self.instance,after).source,self.candidate.source)
        rollback(self.instance,self.candidate.descriptor()['sha256'])
        self.assertEqual(gat.status(self.instance)['integration'],self.original.descriptor())

    @patch('ocn_core.candidate_adoption.evaluate')
    def test_failed_or_equal_candidate_does_not_mutate_manifest(self,evaluate):
        path=self.instance/'instance.json';before=path.read_bytes()
        for reports in ([self.failed,self.failed],[self.passed,self.passed]):
            evaluate.side_effect=reports
            self.assertFalse(adopt(self.instance,self.candidate,self.suite,self.digest)['adopted'])
            self.assertEqual(path.read_bytes(),before)

    @patch('ocn_core.candidate_adoption.evaluate')
    def test_stale_current_digest_does_not_evaluate(self,evaluate):
        with self.assertRaisesRegex(ValueError,'conflict'):adopt(self.instance,self.candidate,self.suite,'0'*64)
        evaluate.assert_not_called()

    @patch('ocn_core.candidate_adoption.evaluate')
    def test_failed_manifest_switch_preserves_current(self,evaluate):
        evaluate.side_effect=[self.failed,self.passed]
        before=(self.instance/'instance.json').read_bytes()
        with patch('ocn_core.candidate_adoption.os.replace',side_effect=OSError('disk error')):
            with self.assertRaises(OSError):adopt(self.instance,self.candidate,self.suite,self.digest)
        self.assertEqual((self.instance/'instance.json').read_bytes(),before)

    @patch('ocn_core.candidate_adoption.evaluate')
    def test_corrupted_previous_revision_blocks_rollback(self,evaluate):
        evaluate.side_effect=[self.failed,self.passed]
        adopt(self.instance,self.candidate,self.suite,self.digest)
        (self.instance/'revisions'/(self.digest+'.py')).write_text('damaged')
        with self.assertRaisesRegex(ValueError,'code changed'):rollback(self.instance,self.candidate.descriptor()['sha256'])
        self.assertEqual(gat.status(self.instance)['integration'],self.candidate.descriptor())

    @patch('ocn_core.candidate_adoption.evaluate')
    def test_broker_budget_unchanged(self,evaluate):
        instance=self.root/'broker'
        gat.create(instance,self.docs,{'a':'a.md'},'When?',integration=self.original,isolated=True,model_calls=2)
        from ocn_core.model_budget import reserve
        reserve(instance,2);before=(instance/'model-budget.json').read_bytes()
        self.suite['cases'][0]['expected']={'request':{'operation':'synthesize','document_ids':['a']}}
        evaluate.side_effect=[self.failed,self.passed]
        adopt(instance,self.candidate,self.suite,self.digest)
        rollback(instance,self.candidate.descriptor()['sha256'])
        self.assertEqual((instance/'model-budget.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
