import copy
import unittest
from unittest.mock import patch
from ocn_core.agent_integration import Integration
from ocn_core.candidate_evaluation import evaluate


class CandidateEvaluationTests(unittest.TestCase):
    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_empty_abstention_contract_matches_runtime(self,trial):
        self.suite['cases'][0]['expected']={'response':dict(answer='',abstain=True,citations=[])}
        trial.return_value=dict(status='completed',result=dict(response=dict(answer='',abstain=True,citations=[]),usage={}))
        self.assertTrue(evaluate(self.integration,self.suite)['accepted'])
        self.suite['cases'][0]['expected']['response']['abstain']=False
        with self.assertRaises(ValueError):evaluate(self.integration,self.suite)

    def setUp(self):
        self.integration=Integration(b'def build_synthesizer(model): return None\n','build_synthesizer')
        self.response=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')])
        self.suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='first',question='When?',
            documents=[dict(document_id='a',text='Friday')],expected={'response':self.response})])

    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_exact_expected_and_no_oracle_in_candidate_input(self,trial):
        trial.return_value=dict(status='completed',result=dict(response=self.response,usage={'passed':True}))
        report=evaluate(self.integration,self.suite)
        self.assertTrue(report['accepted']);self.assertFalse(report['promoted'])
        self.assertNotIn('expected',trial.call_args.kwargs)
        self.assertEqual(set(trial.call_args.kwargs),{'model','question','documents'})
        altered=copy.deepcopy(self.suite);altered['cases'][0]['question']='Different question'
        self.assertNotEqual(evaluate(self.integration,altered)['suite_sha256'],report['suite_sha256'])

    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_claimed_success_and_wrong_answer_do_not_pass(self,trial):
        for value in ({'accepted':True},{'response':self.response},dict(response=dict(self.response,answer='Monday'),usage={'passed':True}),
                      dict(response=dict(self.response,abstain=0),usage={})):
            trial.return_value=dict(status='completed',result=value)
            self.assertFalse(evaluate(self.integration,self.suite)['accepted'])

    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_validate_all_cases_before_any_execution(self,trial):
        self.suite['cases'].append(copy.deepcopy(self.suite['cases'][0]))
        with self.assertRaises(ValueError):evaluate(self.integration,self.suite)
        trial.assert_not_called()

    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_sandbox_failure_and_missing_capability_fail_closed(self,trial):
        trial.return_value={'status':'failed'}
        self.assertFalse(evaluate(self.integration,self.suite)['accepted'])
        trial.side_effect=RuntimeError('No sandbox')
        with self.assertRaises(RuntimeError):evaluate(self.integration,self.suite)

    @patch('ocn_core.candidate_evaluation.run_trial')
    def test_broker_contract_without_model_call(self,trial):
        expected={'request':{'operation':'synthesize','document_ids':['a']}}
        self.suite['cases'][0]['expected']=expected
        trial.return_value=dict(status='completed',result=expected)
        self.assertTrue(evaluate(self.integration,self.suite)['accepted'])
        trial.return_value=dict(status='completed',result={'request':dict(expected['request'],model='other')})
        self.assertFalse(evaluate(self.integration,self.suite)['accepted'])

if __name__=='__main__':unittest.main()
