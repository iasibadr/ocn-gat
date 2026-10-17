import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ocn_core import gat
from ocn_core.run_feedback import prepare,save,feedback,retire_feedback


class FeedbackRetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.docs=root/'docs';self.docs.mkdir();(self.docs/'a.md').write_text('Friday')
        self.instance=root/'instance';self.reservoir=root/'reservoir';self.reservoir.mkdir()
        gat.create(self.instance,self.docs,{'a':'a.md'},'When?',model='fixture')
        _,config=gat.load(self.instance);directory=prepare(self.instance)
        # Synthetic host receipts: this test does not invoke a language model.
        self.receipts=[save(directory,config,'When?','fixture',{'document_bytes_read':6,'answer':'Friday'}) for _ in range(40)]
        for receipt in self.receipts:self.evaluate(receipt['run_id'])
        self.action=self.receipts[0]['action']

    def evaluate(self,ident):return feedback(self.instance,ident,rubric='fixture',success=True,quality=1.,interventions=0)

    def test_cli_retirement_preserves_estimate_and_retired_replay(self):
        before=self.evaluate(self.receipts[0]['run_id'])['estimate']
        cli=subprocess.run([sys.executable,'-m','ocn_core.gat','retire-feedback',str(self.instance),
            '--action',self.action,'--rubric','fixture','--reservoir',str(self.reservoir)],
            capture_output=True,text=True,timeout=15,check=True)
        receipt=json.loads(cli.stdout)
        self.assertEqual(receipt['retired'],8);self.assertFalse(receipt['run_receipts_removed'])
        after=self.evaluate(self.receipts[0]['run_id'])
        self.assertFalse(after['recorded']);self.assertEqual(after['estimate'],before)
        self.assertEqual(len(list((self.instance/'run-receipts').glob('*.json'))),40)

    def test_instance_and_habitat_are_not_reservoirs(self):
        for target in (self.instance,self.docs,self.instance.parent):
            with self.assertRaisesRegex(ValueError,'separate'):
                retire_feedback(self.instance,self.action,rubric='fixture',reservoir=target)
        link=self.reservoir.parent/'link';link.symlink_to(self.reservoir)
        with self.assertRaisesRegex(ValueError,'symlink'):
            retire_feedback(self.instance,self.action,rubric='fixture',reservoir=link)

    def test_explicit_retirement_can_run_paused_without_resuming(self):
        gat.set_paused(self.instance,True)
        receipt=retire_feedback(self.instance,self.action,rubric='fixture',reservoir=self.reservoir,limit=2)
        self.assertEqual(receipt['retired'],2)
        self.assertEqual(gat.status(self.instance)['lifecycle'],'paused')

    def test_unknown_contract_is_not_created(self):
        before=list((self.instance/'feedback-memory').iterdir())
        with self.assertRaisesRegex(ValueError,'Existing feedback'):
            retire_feedback(self.instance,self.action,rubric='unknown',reservoir=self.reservoir)
        self.assertEqual(list((self.instance/'feedback-memory').iterdir()),before)


if __name__=='__main__':unittest.main()
