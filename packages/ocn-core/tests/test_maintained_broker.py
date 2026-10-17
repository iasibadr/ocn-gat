"""Real request sandboxes with deterministic host-model substitutes; no inference."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.maintenance_policy import configure,status,authority
from ocn_core.maintained_run import run_maintained
from ocn_core.run_feedback import RecordedRunError,feedback

SOURCE=b'''def build_synthesizer(model):
    def request(question,documents):
        return dict(request=dict(operation='synthesize',document_ids=[d['document_id'].lower() for d in documents]))
    return request
'''
DIGEST='a'*64


class MaintainedBrokerTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);self.docs=root/'docs';self.docs.mkdir()
        (self.docs/'a.md').write_text('Friday')
        self.instance=root/'instance'
        gat.create(self.instance,self.docs,{'Schedule':'a.md'},'When?',model='fixture',
                   integration=Integration(SOURCE,'build_synthesizer'),isolated=True,model_calls=2)
        self.suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='identity',question='When?',
            documents=[dict(document_id='Schedule',text='Friday')],
            expected=dict(request=dict(operation='synthesize',document_ids=['Schedule'])))])
        configure(self.instance,'Preserve exact document identifiers.',self.suite,'unavailable',root/'audit',1,preserve_acceptance=True)
        self.catalogue=patch('ocn_core.local_models.require_model',return_value={'digest':DIGEST}).start()
        self.addCleanup(patch.stopall)
        self.model=patch('ocn_core.model_broker.LocalDocumentSynthesizer.__call__').start()
        self.model.return_value=dict(response=dict(answer='Friday',abstain=False,
            citations=[dict(document_id='Schedule',quote='Friday')]),usage={'model_digest':DIGEST})

    def run_recorded(self):
        return run_maintained(self.instance,repair_on_failure=True,record=True,feedback_scope='document_versions')

    def test_repair_then_two_missions_spend_only_two_model_attempts(self):
        first=self.run_recorded()
        self.assertEqual(first['maintenance_result']['status'],'adopted')
        self.assertEqual(first['maintenance_result']['designer_calls'],0)
        self.assertIn('not answer correctness',first['acceptance_scope'])
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],1)
        self.assertTrue(feedback(self.instance,first['run_receipt']['run_id'],rubric='exact',success=True,quality=1,interventions=0)['recorded'])
        (self.docs/'a.md').rename(self.docs/'moved.md')
        second=self.run_recorded()
        self.assertEqual(second['citations'][0]['path'],'moved.md')
        self.assertEqual(second['maintenance_result']['status'],'not_needed')
        self.assertEqual(first['run_receipt']['context'],second['run_receipt']['context'])
        with self.assertRaisesRegex(RuntimeError,'budget exhausted'):self.run_recorded()
        self.assertEqual(self.model.call_count,2)
        self.assertEqual(status(self.instance)['used_cycles'],1)
        self.assertEqual(len(list((self.instance/'run-receipts').glob('*.json'))),2)

    def test_model_timeout_is_one_failed_mission_without_repair_retry(self):
        self.model.side_effect=TimeoutError('private backend message')
        with self.assertRaises(RecordedRunError) as caught:self.run_recorded()
        self.assertEqual(caught.exception.receipt['status'],'failed')
        self.assertEqual(self.model.call_count,1)
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],1)
        self.assertEqual(status(self.instance)['used_cycles'],1)
        self.assertNotIn('private backend',json.dumps(caught.exception.receipt))

    def test_request_acceptance_does_not_certify_semantic_answer(self):
        self.model.return_value['response']['answer']='Monday'  # Structurally valid but false.
        result=self.run_recorded()
        self.assertEqual(result['answer'],'Monday')
        self.assertFalse((self.instance/'feedback-memory').exists())
        observed=feedback(self.instance,result['run_receipt']['run_id'],rubric='exact',success=False,quality=0,interventions=1)
        self.assertEqual(observed['estimate']['expected_return'],0)

    def test_learned_repair_requires_new_observations_before_inference(self):
        # The broken integration must reach its acceptance gate before selection.
        with self.assertRaisesRegex(RuntimeError,'No sufficiently observed'):
            run_maintained(self.instance,repair_on_failure=True,learned_models=['fixture'],
                           feedback_rubric='exact',minimum_observations=1)
        self.assertEqual(status(self.instance)['used_cycles'],1)
        self.model.assert_not_called()
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],0)
        self.assertFalse(list((self.instance/'run-receipts').glob('*.json')))
        first=self.run_recorded()
        feedback(self.instance,first['run_receipt']['run_id'],rubric='exact',success=True,quality=1,interventions=0)
        result=run_maintained(self.instance,repair_on_failure=True,learned_models=['fixture'],
                             feedback_rubric='exact',minimum_observations=1,feedback_scope='document_versions')
        self.assertEqual(result['learned_selection']['model'],'fixture')
        self.assertEqual(result['maintenance_result']['status'],'not_needed')
        self.assertEqual(self.model.call_count,2)
        self.assertEqual(status(self.instance)['used_cycles'],1)

    def test_previous_revision_reward_is_not_inherited_after_repair(self):
        instance=self.instance.parent/'lowercase-instance'
        gat.create(instance,self.docs,{'schedule':'a.md'},'When?',model='fixture',
                   integration=Integration(SOURCE,'build_synthesizer'),isolated=True,model_calls=2)
        configure(instance,'Preserve exact identifiers including case.',self.suite,'unavailable',
                  self.instance.parent/'second-audit',1)
        self.model.return_value['response']['citations'][0]['document_id']='schedule'
        old=gat.run(instance,record=True)
        feedback(instance,old['run_receipt']['run_id'],rubric='exact',success=True,quality=1,interventions=0)
        before=gat.load(instance)[1]['integration']['sha256']
        with self.assertRaisesRegex(RuntimeError,'No sufficiently observed'):
            run_maintained(instance,repair_on_failure=True,learned_models=['fixture'],
                           feedback_rubric='exact',minimum_observations=1)
        self.assertNotEqual(before,gat.load(instance)[1]['integration']['sha256'])
        self.assertEqual(status(instance)['used_cycles'],1)
        self.assertEqual(self.model.call_count,1)
        self.assertEqual(gat.status(instance)['model_budget']['used'],1)
        self.assertEqual(len(list((instance/'run-receipts').glob('*.json'))),1)

    def test_invalid_selection_does_not_spend_repair_cycle(self):
        for options in (dict(learned_models=['unauthorized'],feedback_rubric='exact'),
                        dict(learned_models=['fixture'],feedback_rubric=None),
                        dict(learned_models=['fixture'],feedback_rubric='exact',minimum_observations=0)):
            with self.assertRaises(ValueError):run_maintained(self.instance,**options)
        self.assertEqual(status(self.instance)['used_cycles'],0)
        self.model.assert_not_called()
        self.catalogue.assert_not_called()

    def test_incompatible_suite_and_pause_prevent_model_use(self):
        _,config=gat.load(self.instance)
        bad=json.loads(json.dumps(self.suite))
        bad['cases'][0]['expected']=dict(response=dict(answer='Friday',abstain=False,citations=[dict(document_id='Schedule',quote='Friday')]))
        with self.assertRaisesRegex(ValueError,'contract mismatch'):
            gat.run(self.instance,acceptance_suite=bad,expected_authority=authority(config))
        gat.set_paused(self.instance,True)
        with self.assertRaisesRegex(RuntimeError,'paused'):self.run_recorded()
        self.model.assert_not_called()
        self.assertEqual(status(self.instance)['used_cycles'],0)
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],0)

if __name__=='__main__':unittest.main()
