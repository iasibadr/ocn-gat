import unittest
from unittest.mock import Mock,patch
from ocn_core.agent_integration import Integration
from ocn_core.model_broker import BrokeredSynthesizer


class ModelBrokerTests(unittest.TestCase):
    def setUp(self):
        self.integration=Integration(b'def build_synthesizer(model): return None\n','build_synthesizer')
        self.model=Mock(return_value=dict(response=dict(answer='Friday',abstain=False,
            citations=[dict(document_id='a',quote='Friday')]),usage={'model_calls':1}))
        self.broker=BrokeredSynthesizer(self.integration,'host-chosen',synthesizer=self.model)
        self.docs=[dict(document_id='a',sha256='a'*64,text='Friday'),dict(document_id='b',sha256='b'*64,text='Monday')]

    def trial(self,value):return dict(status='completed',result=value,source_sha256=self.integration.descriptor()['sha256'])

    @patch('ocn_core.model_broker.run_trial')
    def test_exact_host_inputs_once(self,run):
        run.return_value=self.trial({'request':{'operation':'synthesize','document_ids':['a']}})
        answer=self.broker('Original question',self.docs)
        self.model.assert_called_once_with('Original question',[self.docs[0]])
        self.assertEqual(answer['usage']['host_synthesis_calls'],1)
        self.assertEqual(run.call_args.kwargs['model'],'host-chosen')

    @patch('ocn_core.model_broker.run_trial')
    def test_untrusted_options_and_unknown_documents_rejected_before_model(self,run):
        requests=[{'operation':'shell','document_ids':['a']},
            {'operation':'synthesize','document_ids':['a'],'model':'other'},
            {'operation':'synthesize','document_ids':['a'],'question':'changed'},
            {'operation':'synthesize','document_ids':['a'],'url':'http://example.invalid'},
            {'operation':'synthesize','document_ids':['unknown']},
            {'operation':'synthesize','document_ids':['a','a']},
            {'operation':'synthesize','document_ids':[]}]
        for request in requests:
            run.return_value=self.trial({'request':request})
            with self.assertRaises(ValueError):self.broker('Question',self.docs)
        self.model.assert_not_called()

    @patch('ocn_core.model_broker.run_trial')
    def test_no_retry_or_host_fallback(self,run):
        run.return_value={'status':'failed'}
        with self.assertRaises(RuntimeError):self.broker('Question',self.docs)
        self.model.assert_not_called()
        run.return_value=self.trial({'request':{'operation':'synthesize','document_ids':['a']}})
        self.model.side_effect=TimeoutError('Model timeout')
        with self.assertRaises(TimeoutError):self.broker('Question',self.docs)
        self.model.assert_called_once()

    @patch('ocn_core.model_broker.run_trial')
    def test_citation_outside_selected_context_rejected(self,run):
        run.return_value=self.trial({'request':{'operation':'synthesize','document_ids':['b']}})
        with self.assertRaisesRegex(ValueError,'outside selected'):self.broker('Question',self.docs)

if __name__=='__main__':unittest.main()
