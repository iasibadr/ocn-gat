"""Do not infer version-specific competence from different source contents."""
import hashlib
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_run_feedback as fixtures
from ocn_core import gat
from ocn_core.run_feedback import RecordedRunError, context_id


class FeedbackVersionTests(unittest.TestCase):
    setUp=fixtures.RunFeedbackTests.setUp
    score=fixtures.RunFeedbackTests.score

    def train(self,scope):
        receipts=[]
        for _ in range(3):
            receipt=gat.run(self.instance,record=True,model='A',feedback_scope=scope)['run_receipt']
            self.score(receipt['run_id']);receipts.append(receipt)
        return receipts

    def learned(self,scope):
        return gat.run(self.instance,learned_models=['A'],feedback_rubric='exact-answer-v1',feedback_scope=scope)

    def update(self):
        path=self.instance.parent/'docs'/'a.md'
        path.write_text('Monday')
        gat.update_document(self.instance,'a','a.md',hashlib.sha256(b'Friday').hexdigest(),hashlib.sha256(b'Monday').hexdigest())

    def test_relocation_keeps_experience_but_new_version_requires_evidence(self):
        old=self.train('document_versions')[0]
        docs=self.instance.parent/'docs'
        (docs/'a.md').rename(docs/'moved.md')
        moved=self.learned('document_versions')
        self.assertEqual(moved['run_receipt']['context'],old['context'])
        self.assertEqual(moved['citations'][0]['path'],'moved.md')
        (docs/'moved.md').rename(docs/'a.md');self.update()
        with patch('ocn_core.gat.DocumentAgent.answer') as answer:
            with self.assertRaisesRegex(RuntimeError,'sufficiently'):self.learned('document_versions')
            answer.assert_not_called()
        new=self.train('document_versions')[0]
        self.assertNotEqual(old['context'],new['context'])
        self.assertEqual(self.learned('document_versions')['answer'],'Monday')
        self.assertFalse(self.score(old['run_id'])['recorded'])

    def test_mission_scope_compatible_but_not_imported_into_version_scope(self):
        old=self.train('mission')[0];self.update()
        self.assertEqual(self.learned('mission')['run_receipt']['context'],old['context'])
        with self.assertRaisesRegex(RuntimeError,'sufficiently'):self.learned('document_versions')
        _,config=gat.load(self.instance)
        self.assertEqual(old['context'],context_id(config,'When?'))
        with self.assertRaises(ValueError):context_id(config,'When?',{})
        with self.assertRaises(ValueError):gat.run(self.instance,feedback_scope='other',record=True)
        with self.assertRaisesRegex(ValueError,'recording'):gat.run(self.instance,feedback_scope='document_versions')

    def test_cli_and_failed_mission_share_enrolled_version_context(self):
        command=[sys.executable,'-m','ocn_core.gat','run',str(self.instance),'--record','--feedback-scope','document_versions']
        result=subprocess.run(command,capture_output=True,text=True,check=True,timeout=30)
        good=json.loads(result.stdout)['run_receipt']
        self.assertEqual(good['feedback_scope'],'document_versions')
        (self.instance.parent/'docs'/'a.md').write_text('Unauthorized replacement')
        with self.assertRaises(RecordedRunError) as caught:
            gat.run(self.instance,record=True,feedback_scope='document_versions')
        self.assertEqual(caught.exception.receipt['context'],good['context'])
        self.assertEqual(caught.exception.receipt['status'],'failed')
        self.assertTrue(self.score(caught.exception.receipt['run_id'],success=False,quality=0)['recorded'])

if __name__=='__main__':unittest.main()
