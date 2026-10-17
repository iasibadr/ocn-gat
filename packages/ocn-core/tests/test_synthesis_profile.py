import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.document_agent import LocalDocumentSynthesizer,ANSWERABILITY_SUFFIX
from ocn_core.context_budget import select_context
from ocn_core.run_feedback import action_id,digest
from ocn_core.maintenance_policy import configure,authority
from ocn_core.maintained_run import run_maintained

SOURCE=b'''def build_synthesizer(model):
    def request(question,documents):
        return dict(request=dict(operation='synthesize',document_ids=[d['document_id'] for d in documents]))
    return request
'''

class SynthesisProfileTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        (self.docs/'a.md').write_text('Friday')

    def test_profile_expands_prompt_before_context_sizing_and_keeps_strict_fields(self):
        answer=dict(answer='Friday',citations=[dict(document_id='a',quote='Friday')])
        raw=json.dumps(dict(done=True,done_reason='stop',prompt_eval_count=200,eval_count=20,message=dict(content=json.dumps(answer)))).encode()
        with patch('ocn_core.document_agent.require_model',return_value={'digest':'a'*64}),patch('ocn_core.document_agent.urllib.request.urlopen',return_value=io.BytesIO(raw)) as call:
            result=LocalDocumentSynthesizer('fixture',profile='answerability-v1')('When?',[dict(document_id='a',text='Friday')])
        payload=json.loads(call.call_args.args[0].data)
        self.assertTrue(payload['messages'][0]['content'].endswith(ANSWERABILITY_SUFFIX+json.dumps(payload['format'],sort_keys=True)))
        self.assertEqual(result['usage']['context_request'],select_context(payload['messages'],512))
        self.assertNotIn('abstain',result['response']) # Never invent a missing field.
        self.assertEqual(call.call_count,1)

    def test_manifest_and_experience_identity_preserve_legacy_and_separate_profile(self):
        gat.create(self.root/'legacy',self.docs,{'a':'a.md'},'When?')
        gat.create(self.root/'new',self.docs,{'a':'a.md'},'When?',synthesis_profile='answerability-v1')
        _,old=gat.load(self.root/'legacy');_,new=gat.load(self.root/'new')
        self.assertNotIn('synthesis_profile',old)
        self.assertEqual(action_id(old,'fixture'),digest(dict(format=old['format'],integration=None,model='fixture')))
        self.assertNotEqual(action_id(old,'fixture'),action_id(new,'fixture'))
        self.assertNotEqual(authority(old),authority(new))
        with self.assertRaisesRegex(ValueError,'profile'):
            gat.create(self.root/'bad',self.docs,{'a':'a.md'},'When?',integration=Integration(SOURCE,'build_synthesizer'),isolated=True,synthesis_profile='answerability-v1')
        self.assertFalse((self.root/'bad').exists())

    def test_maintained_broker_uses_profile_without_extra_calls(self):
        instance=self.root/'agent'
        gat.create(instance,self.docs,{'a':'a.md'},'When?',model='fixture',integration=Integration(SOURCE,'build_synthesizer'),isolated=True,model_calls=1,synthesis_profile='answerability-v1')
        suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='one',question='When?',documents=[dict(document_id='a',text='Friday')],expected=dict(request=dict(operation='synthesize',document_ids=['a'])))])
        configure(instance,'Use authorized documents.',suite,'unavailable',self.root/'audit',1)
        def synth(model,question,documents):
            self.assertEqual(model.profile,'answerability-v1')
            return dict(response=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')]),usage={'model_digest':'a'*64})
        with patch('ocn_core.local_models.require_model',return_value={'digest':'a'*64}),patch.object(LocalDocumentSynthesizer,'__call__',autospec=True,side_effect=synth) as call:
            result=run_maintained(instance,repair_on_failure=True,record=True)
        self.assertEqual(result['answer'],'Friday');self.assertEqual(call.call_count,1)
        self.assertEqual(gat.status(instance)['model_budget']['used'],1)
        _,config=gat.load(instance)
        self.assertEqual(result['run_receipt']['action'],action_id(config,'fixture','a'*64))

    def test_cli_create_persists_explicit_profile(self):
        subprocess.run([sys.executable,'-m','ocn_core.gat','create',str(self.root/'cli'),'--habitat',str(self.docs),'--document','a=a.md','--mission','When?','--synthesis-profile','answerability-v1'],capture_output=True,text=True,check=True,timeout=30)
        self.assertEqual(gat.load(self.root/'cli')[1]['synthesis_profile'],'answerability-v1')

if __name__=='__main__':unittest.main()
