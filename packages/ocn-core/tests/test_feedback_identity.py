from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.run_feedback import feedback


class FeedbackIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);docs=root/'docs';docs.mkdir();(docs/'a.md').write_text('Friday')
        self.instance=root/'agent';gat.create(self.instance,docs,{'a':'a.md'},'When?',model='same-tag')
        self.digest='a'*64
        self.registry=patch('ocn_core.local_models.require_model',side_effect=lambda m:{'digest':self.digest})
        self.registry.start();self.addCleanup(self.registry.stop)
        self.answer=patch('ocn_core.gat.DocumentAgent.answer',side_effect=self.result)
        self.answer.start();self.addCleanup(self.answer.stop)

    def result(self,*args):
        return dict(answer='Friday',abstain=False,citations=[],document_bytes_read=6,
                    usage={'model_digest':self.digest})

    def seed(self):
        for _ in range(3):
            receipt=gat.run(self.instance,record=True)['run_receipt']
            feedback(self.instance,receipt['run_id'],rubric='test',success=True,quality=1.,interventions=0)

    def learned(self):return gat.run(self.instance,learned_models=['same-tag'],feedback_rubric='test')

    def test_same_tag_new_digest_has_no_inherited_success(self):
        self.seed();self.assertEqual(self.learned()['run_receipt']['model_digest'],'a'*64)
        self.digest='b'*64
        with self.assertRaisesRegex(RuntimeError,'sufficiently'):self.learned()
        self.seed();self.assertEqual(self.learned()['run_receipt']['model_digest'],'b'*64)
        self.digest='a'*64
        self.assertEqual(self.learned()['learned_selection']['candidates'][0]['observations'],3)

    def test_identity_change_during_selection_prevents_inference(self):
        self.seed()
        with patch('ocn_core.local_models.require_model',side_effect=[{'digest':'a'*64},{'digest':'b'*64}]), \
             patch('ocn_core.gat.DocumentAgent.answer') as answer:
            with self.assertRaisesRegex(ValueError,'during selection'):self.learned()
            answer.assert_not_called()

    def test_mismatched_reported_identity_is_not_attributed(self):
        with patch('ocn_core.gat.DocumentAgent.answer',return_value=dict(document_bytes_read=6,usage={'model_digest':'b'*64})):
            with self.assertRaisesRegex(ValueError,'not attributed'):gat.run(self.instance,record=True)
        self.assertEqual(list((self.instance/'run-receipts').iterdir()),[])

    def test_invalid_catalogue_digest_is_rejected(self):
        self.digest='not-an-identity'
        with self.assertRaisesRegex(ValueError,'digest'):gat.run(self.instance,record=True)


if __name__=='__main__':unittest.main()
