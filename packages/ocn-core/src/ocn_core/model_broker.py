"""One host-owned synthesis request from an offline, untrusted candidate."""
from .agent_integration import Integration
from .document_agent import LocalDocumentSynthesizer
from .sandbox_trial import run_trial


class BrokeredSynthesizer:
    def __init__(self,integration,model,*,synthesizer=None,reserve_call=None,synthesis_profile='standard'):
        if type(integration) is not Integration:raise ValueError('Prepared integration required')
        integration.descriptor()
        self.integration=integration;self.model=model
        self.reserve_call=reserve_call
        self.synthesizer=LocalDocumentSynthesizer(model,profile=synthesis_profile) if synthesizer is None else synthesizer

    def __call__(self,question,documents):
        trial=run_trial(self.integration,model=self.model,question=question,documents=documents)
        if trial['status']!='completed':raise RuntimeError('Isolated model request failed')
        value=trial['result']
        if type(value) is not dict or set(value)!={'request'}:raise ValueError('Invalid model request envelope')
        request=value['request']
        if (type(request) is not dict or set(request)!={'operation','document_ids'}
            or request['operation']!='synthesize'):raise ValueError('Unauthorized model request')
        ids=request['document_ids'];known={d['document_id']:d for d in documents}
        if (type(ids) is not list or not 1<=len(ids)<=8
            or any(type(i) is not str or i not in known for i in ids)
            or len(set(ids))!=len(ids)):raise ValueError('Unauthorized document selection')
        # The candidate cannot supply text, a prompt, model options, a URL or a key.
        # Exactly one invocation; no retries or continuation of candidate execution.
        reservation=self.reserve_call() if self.reserve_call is not None else None
        answer=self.synthesizer(question,[dict(known[i]) for i in ids])
        if (type(answer) is not dict or set(answer)!={'response','usage'}
            or type(answer['usage']) is not dict or type(answer['response']) is not dict):
            raise ValueError('Invalid broker synthesis envelope')
        citations=answer['response'].get('citations')
        if (type(citations) is not list or any(type(c) is not dict
            or c.get('document_id') not in ids for c in citations)):
            raise ValueError('Broker citation outside selected documents')
        # Full schema, exact quotes and freshness are checked by DocumentAgent.
        return dict(response=answer['response'],usage=dict(execution='bubblewrap_host_model_broker',
            source_sha256=trial['source_sha256'],host_synthesis_calls=1,
            selected_document_ids=ids,budget_reservation=reservation,model_usage=answer['usage']))
