"""Bounded persistent model authority, shared attempts and observed selection."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.document_agent import LocalDocumentSynthesizer
from ocn_core.run_feedback import feedback
from ocn_core.maintenance_policy import authority

SOURCE=b'''def build_synthesizer(model):
    def request(question,documents):
        return dict(request=dict(operation='synthesize',document_ids=[d['document_id'] for d in documents]))
    return request
'''

class BrokerCatalogueTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.docs=self.root/'docs';self.docs.mkdir();(self.docs/'a.md').write_text('Friday')
        self.instance=self.root/'agent';self.create(self.instance,['A','B'],10)
        self.called=[]
        def synth(synthesizer,question,documents):
            self.called.append(synthesizer.model)
            return dict(response=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')]),usage={'model_digest':self.identity(synthesizer.model)['digest']})
        catalogue=patch('ocn_core.local_models.require_model',side_effect=self.identity);self.lookup=catalogue.start();self.addCleanup(catalogue.stop)
        model=patch.object(LocalDocumentSynthesizer,'__call__',autospec=True,side_effect=synth);model.start();self.addCleanup(model.stop)

    @staticmethod
    def identity(name):return {'digest':('a' if name=='A' else 'b')*64}

    def create(self,path,models,limit=9,**kw):
        return gat.create(path,self.docs,{'a':'a.md'},'When?',model='A',integration=Integration(SOURCE,'build_synthesizer'),isolated=True,model_calls=limit,authorized_models=models,**kw)

    def observed(self,model,success):
        result=gat.run(self.instance,model=model,record=True)
        feedback(self.instance,result['run_receipt']['run_id'],rubric='host-test',success=success,quality=int(success),interventions=0)
        return result

    def learned(self):return gat.run(self.instance,learned_models=['A','B'],feedback_rubric='host-test')

    def test_actual_selected_model_changes_and_all_attempts_share_one_budget(self):
        for success in (True,True,True):self.observed('A',success)
        for success in (True,True,False):self.observed('B',success)
        first=self.learned();self.assertEqual(first['learned_selection']['model'],'A')
        self.observed('A',False)  # First failure ties B: operator order would still choose A.
        self.observed('A',False)
        second=self.learned();self.assertEqual(second['learned_selection']['model'],'B')
        self.assertEqual(self.called,['A']*3+['B']*3+['A','A','A','B'])
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],10)
        self.assertNotEqual(first['run_receipt']['action'],second['run_receipt']['action'])
        with self.assertRaisesRegex(RuntimeError,'budget exhausted'):self.learned()
        self.assertEqual(len(self.called),10)

    def test_maintained_executes_the_observed_winner_and_never_retries_failure(self):
        from ocn_core.maintenance_policy import configure,status
        from ocn_core.maintained_run import run_maintained
        from ocn_core.run_feedback import RecordedRunError
        for _ in range(3):self.observed('A',False)
        for _ in range(3):self.observed('B',True)
        suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='identity',question='When?',
            documents=[dict(document_id='a',text='Friday')],
            expected=dict(request=dict(operation='synthesize',document_ids=['a'])))])
        configure(self.instance,'Keep document identifiers',suite,'unavailable',self.root/'audit',1)
        result=run_maintained(self.instance,repair_on_failure=True,learned_models=['A','B'],feedback_rubric='host-test')
        self.assertEqual(result['learned_selection']['model'],'B')
        self.assertEqual(self.called[-1],'B')
        with patch.object(LocalDocumentSynthesizer,'__call__',side_effect=TimeoutError) as failing:
            with self.assertRaises(RecordedRunError):
                run_maintained(self.instance,repair_on_failure=True,learned_models=['A','B'],feedback_rubric='host-test')
            self.assertEqual(failing.call_count,1)
        self.assertEqual(status(self.instance)['used_cycles'],0)
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],8)

    def test_unauthorized_model_rejected_before_memory_and_model_access(self):
        with patch('ocn_core.memory_maintenance.before_run_locked') as housekeeping:
            for kw in ({'model':'C','record':True},{'learned_models':['A','C'],'feedback_rubric':'host-test'}):
                with self.assertRaisesRegex(ValueError,'authorization'):gat.run(self.instance,**kw)
            housekeeping.assert_not_called()
        self.lookup.assert_not_called();self.assertFalse(self.called)
        self.assertFalse((self.instance/'run-receipts').exists())
        self.assertEqual(gat.status(self.instance)['model_budget']['used'],0)

    def test_legacy_pin_and_authority_are_preserved(self):
        old=self.root/'old';self.create(old,None)
        _,config=gat.load(old);_,new=gat.load(self.instance)
        self.assertNotIn('authorized_models',config)
        # Compare same habitat/mission/format, only the explicit catalogue changes.
        self.assertNotEqual(authority(config),authority(new))
        with self.assertRaisesRegex(ValueError,'cannot be overridden'):gat.run(old,model='B')
        with self.assertRaisesRegex(ValueError,'cannot be overridden'):gat.run(old,learned_models=['A','B'],feedback_rubric='host-test')
        self.assertFalse(self.called)

    def test_cli_adapt_persists_catalogue_without_inference(self):
        bridge=self.root/'bridge.py';bridge.write_bytes(SOURCE)
        plan=self.root/'plan.json'
        plan.write_text(json.dumps(dict(format='gat.document-plan.v1',habitat=str(self.docs),mission='When?',runtime_model='A',
            abstain=False,rationale='Host fixture',designer_usage={},documents=[dict(document_id='a',path='a.md',sha256=hashlib.sha256(b'Friday').hexdigest())])))
        instance=self.root/'cli'
        subprocess.run([sys.executable,'-m','ocn_core.gat','adapt',str(instance),'--plan',str(plan),'--agent-file',str(bridge),
            '--isolated','--model-calls','2','--authorized-models','A','B'],capture_output=True,text=True,check=True,timeout=30)
        self.assertEqual(gat.load(instance)[1]['authorized_models'],['A','B'])
        self.assertEqual(gat.status(instance)['model_budget']['used'],0)

    def test_bad_catalogues_fail_before_creating_instance(self):
        for index,models in enumerate(([],['B'],['A','A'],['A',False],['A']+[f'M{i}' for i in range(8)],'A')):
            path=self.root/f'bad{index}'
            with self.assertRaises(ValueError):self.create(path,models)
            self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
