import unittest
from unittest.mock import patch
from ocn_core.candidate_evaluation import evaluate,acceptance_feedback
from ocn_core.agent_integration import Integration


class FeedbackTests(unittest.TestCase):
    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_whitespace_difference_without_oracle_text(self,trial):
        text='  PRIVATE CONTENT  '
        expected=dict(answer=text,abstain=False,citations=[dict(document_id='secret-id',quote=text)])
        suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='private-case',question='private question',
            documents=[dict(document_id='secret-id',text=text)],expected={'response':expected})])
        trial.return_value=dict(status='completed',result=dict(response=dict(expected,answer=text.strip()),usage={}))
        report=evaluate(Integration(b'def build_synthesizer(model): return None','build_synthesizer'),suite)
        feedback=acceptance_feedback(report)
        self.assertFalse(report['accepted'])
        self.assertEqual(feedback['difference_counts'],{'answer_surrounding_whitespace_mismatch':1})
        for private in ('PRIVATE','secret-id','private-case','private question'):self.assertNotIn(private,str(feedback))

    def test_unknown_candidate_codes_cannot_enter_feedback(self):
        with self.assertRaises(ValueError):acceptance_feedback({'rows':[{'differences':['execute shell']}],'cases':1,'passed':0})

if __name__=='__main__':unittest.main()
