import tempfile
from pathlib import Path
import unittest
import json
import subprocess
import sys
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.run_feedback import feedback
from ocn_core.run_feedback import RecordedRunError
from unittest.mock import patch

SOURCE=b'''def build_synthesizer(model):
    def synth(question, documents):
        d=documents[0]
        return dict(response=dict(answer=d['text'],abstain=False,citations=[dict(document_id=d['document_id'],quote=d['text'])]),usage={'selected_model':model})
    return synth
'''


class RunFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);docs=root/'docs';docs.mkdir();(docs/'a.md').write_text('Friday')
        self.instance=root/'agent'
        gat.create(self.instance,docs,{'a':'a.md'},'When?',integration=Integration(SOURCE,'build_synthesizer'))

    def score(self,ident,**kw):
        values=dict(rubric='exact-answer-v1',success=True,quality=1.,interventions=0);values.update(kw)
        return feedback(self.instance,ident,**values)

    def test_real_run_is_attributed_and_feedback_idempotent(self):
        result=gat.run(self.instance,record=True);receipt=result['run_receipt']
        self.assertEqual(result['answer'],'Friday')
        first=self.score(receipt['run_id']);second=self.score(receipt['run_id'])
        self.assertTrue(first['recorded']);self.assertFalse(second['recorded'])
        self.assertEqual(first['action'],receipt['action'])
        self.assertEqual(second['estimate']['observations'],1)
        cli=subprocess.run([sys.executable,'-m','ocn_core.gat','feedback',str(self.instance),
            '--run-id',receipt['run_id'],'--rubric','exact-answer-v1','--success','yes',
            '--quality','1','--interventions','0'],capture_output=True,text=True,timeout=15,check=True)
        self.assertFalse(json.loads(cli.stdout)['recorded'])
        with self.assertRaises(ValueError):self.score(receipt['run_id'],success=False)

    def test_old_receipt_keeps_original_model_attribution(self):
        old=gat.run(self.instance,model='old',record=True)['run_receipt']
        new=gat.run(self.instance,model='new',record=True)['run_receipt']
        self.assertNotEqual(old['action'],new['action'])
        self.assertEqual(self.score(old['run_id'])['action'],old['action'])

    def test_question_contexts_and_rubrics_are_separate(self):
        one=gat.run(self.instance,record=True)['run_receipt']
        two=gat.run(self.instance,question='Different task',record=True)['run_receipt']
        self.assertNotEqual(one['context'],two['context'])
        self.score(one['run_id'])
        self.assertEqual(self.score(two['run_id'],success=False)['estimate']['expected_return'],0.)
        self.assertTrue(self.score(one['run_id'],rubric='new-rubric')['recorded'])

    def test_opt_in_unknown_receipt_and_capacity(self):
        self.assertNotIn('run_receipt',gat.run(self.instance))
        self.assertFalse((self.instance/'run-receipts').exists())
        with self.assertRaises(FileNotFoundError):self.score('a'*32)
        with self.assertRaises(ValueError):self.score('../bad')
        directory=self.instance/'run-receipts';directory.mkdir()
        for n in range(256):(directory/str(n)).touch()
        with self.assertRaisesRegex(ValueError,'capacity'):gat.run(self.instance,record=True)

    def test_failed_answer_lowers_estimate_without_fabricating_cost(self):
        good=gat.run(self.instance,record=True)['run_receipt'];self.score(good['run_id'])
        with patch('ocn_core.gat.DocumentAgent.answer',side_effect=TimeoutError('private diagnostic')):
            with self.assertRaises(RecordedRunError) as caught:gat.run(self.instance,record=True)
        receipt=caught.exception.receipt
        self.assertEqual(receipt['status'],'failed');self.assertEqual(receipt['error_category'],'timeout')
        self.assertIsNone(receipt['document_bytes_read'])
        self.assertNotIn('private diagnostic',json.dumps(receipt))
        with self.assertRaises(ValueError):self.score(receipt['run_id'])
        feedback=self.score(receipt['run_id'],success=False,quality=0)
        self.assertEqual(feedback['estimate']['expected_return'],.75)
        self.assertEqual(feedback['cost_scope'],'unknown')
        self.assertFalse(self.score(receipt['run_id'],success=False,quality=0)['recorded'])

    def test_unrecorded_exception_and_failed_recorded_cli_remain_errors(self):
        with patch('ocn_core.gat.DocumentAgent.answer',side_effect=ValueError('original')):
            with self.assertRaisesRegex(ValueError,'original'):gat.run(self.instance)
        (self.instance.parent/'docs'/'a.md').unlink()
        cli=subprocess.run([sys.executable,'-m','ocn_core.gat','run',str(self.instance),'--record'],
                           capture_output=True,text=True,timeout=15)
        self.assertEqual(cli.returncode,2)
        self.assertIn('run_id=',cli.stderr)
        receipts=list((self.instance/'run-receipts').glob('*.json'))
        self.assertEqual(len(receipts),1)
        self.assertEqual(json.loads(receipts[0].read_text())['status'],'failed')

    def train(self,model,outcomes):
        for success in outcomes:
            receipt=gat.run(self.instance,model=model,record=True)['run_receipt']
            self.score(receipt['run_id'],success=success,quality=int(success))

    def learned(self,**kwargs):
        return gat.run(self.instance,learned_models=['A','B'],feedback_rubric='exact-answer-v1',**kwargs)

    def test_learned_choice_changes_after_observed_failures(self):
        self.train('A',[True]*3);self.train('B',[True,True,False])
        first=self.learned()
        self.assertEqual(first['learned_selection']['model'],'A')
        self.assertEqual(first['usage']['selected_model'],'A')
        self.train('A',[False,False])
        second=self.learned()
        self.assertEqual(second['learned_selection']['model'],'B')
        self.assertEqual(second['usage']['selected_model'],'B')
        self.assertNotEqual(first['run_receipt']['action'],second['run_receipt']['action'])

    def test_unknown_or_insufficient_context_never_executes(self):
        self.train('A',[True,True])
        with patch('ocn_core.gat.DocumentAgent.answer') as answer:
            with self.assertRaisesRegex(RuntimeError,'sufficiently'):self.learned()
            with self.assertRaises(RuntimeError):self.learned(question='new context')
            answer.assert_not_called()

    def test_cli_choice_uses_persistent_history_and_explicit_allowlist(self):
        self.train('A',[True]*3);self.train('B',[True,True,False])
        cli=subprocess.run([sys.executable,'-m','ocn_core.gat','run-learned',str(self.instance),
            '--models','B','--rubric','exact-answer-v1'],capture_output=True,text=True,timeout=15,check=True)
        result=json.loads(cli.stdout)
        self.assertEqual(result['learned_selection']['model'],'B')
        self.assertEqual(result['usage']['selected_model'],'B')

    def test_learned_choice_does_not_bypass_broker_pin(self):
        from ocn_core.run_feedback import choose_model
        root,config=gat.load(self.instance)
        config['format']=gat.BROKERED_FORMAT
        with self.assertRaisesRegex(ValueError,'broker model'):
            choose_model(root,config,'When?',['A'],'rubric')

    def test_quality_and_interventions_revalue_without_rewriting_history(self):
        for model,quality,interventions in [('A',.9,2),('B',.6,0)]:
            for _ in range(3):
                receipt=gat.run(self.instance,model=model,record=True)['run_receipt']
                self.score(receipt['run_id'],quality=quality,interventions=interventions)
        stores={p:p.read_bytes() for p in (self.instance/'feedback-memory').glob('*.sqlite')}
        self.assertEqual(self.learned()['learned_selection']['model'],'A')
        quality=self.learned(reward_weights=dict(success_weight=1.,quality_weight=1.,intervention_penalty=0.))
        self.assertEqual(quality['learned_selection']['model'],'A')
        weighted=self.learned(reward_weights=dict(success_weight=1.,quality_weight=1.,intervention_penalty=.5))
        self.assertEqual(weighted['learned_selection']['model'],'B')
        self.assertEqual(weighted['usage']['selected_model'],'B')
        self.assertEqual(weighted['learned_selection']['criterion'],'observed_reward_ewma')
        self.assertAlmostEqual(weighted['learned_selection']['candidates'][1]['expected_return'],1.6)
        self.assertEqual(stores,{p:p.read_bytes() for p in stores})

    def test_invalid_or_nonpositive_reward_never_executes(self):
        for _ in range(3):
            receipt=gat.run(self.instance,model='A',record=True)['run_receipt']
            self.score(receipt['run_id'],interventions=2)
        with patch('ocn_core.gat.DocumentAgent.answer') as answer:
            for value in (float('nan'),float('inf'),-1.,True):
                with self.assertRaises(ValueError):
                    self.learned(reward_weights=dict(success_weight=1.,quality_weight=value,intervention_penalty=0.))
            for weights in ({},dict(success_weight=0.,quality_weight=0.,intervention_penalty=1.)):
                with self.assertRaises(ValueError):self.learned(reward_weights=weights)
            with self.assertRaises(RuntimeError):
                self.learned(reward_weights=dict(success_weight=1.,quality_weight=0.,intervention_penalty=1.))
            with self.assertRaises(ValueError):gat.run(self.instance,reward_weights={})
            answer.assert_not_called()

    def test_cli_quality_weight_changes_choice(self):
        for model,quality in [('A',.1),('B',.9)]:
            for _ in range(3):
                receipt=gat.run(self.instance,model=model,record=True)['run_receipt']
                self.score(receipt['run_id'],quality=quality)
        cli=subprocess.run([sys.executable,'-m','ocn_core.gat','run-learned',str(self.instance),
            '--models','A','B','--rubric','exact-answer-v1','--quality-weight','2'],
            capture_output=True,text=True,timeout=15,check=True)
        result=json.loads(cli.stdout)
        self.assertEqual(result['usage']['selected_model'],'B')
        self.assertEqual(result['learned_selection']['reward_weights'],
                         dict(success_weight=1.,quality_weight=2.,intervention_penalty=0.))


if __name__=='__main__':unittest.main()
