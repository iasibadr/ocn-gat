"""Opt-in bounded document session, independent of research experiment imports.

A classical last-success route policy, verified extraction reuse and existing
EvidenceAgent. No claim of semantic proof, quaternion benefit, full restart or
universal adaptation. Trusted workers must identify their revisions accurately.
"""
from threading import RLock
from copy import deepcopy
import hashlib
import json
from .evidence_fallback import POLICY, checked_fallback
from .model_budget import PersistentAttemptBudget
from .document_routes import RouteAdapter
from .evidence_agent import EvidenceAgent
from .extraction_cache import ExtractionCache


class DocumentSession:
    def __init__(self, routes, worker, revision, *, max_model_calls=8, max_requests=32,
                 fallback_worker=None, fallback_revision=None, attempt_budget=None,
                 route_policy='sticky'):
        if not callable(worker) or not callable(revision):raise ValueError('Trusted worker and revision required')
        if type(max_model_calls) is not int or not 1<=max_model_calls<=64:raise ValueError('Model budget must be 1..64')
        if type(max_requests) is not int or not 1<=max_requests<=128:raise ValueError('Request budget must be 1..128')
        self.adapter=RouteAdapter(routes,policy=route_policy)
        if not 1<=len(self.adapter.pinned)<=8:raise ValueError('One to eight document versions required')
        if attempt_budget is not None and type(attempt_budget) is not PersistentAttemptBudget:
            raise ValueError('PersistentAttemptBudget required')
        self.attempt_budget=attempt_budget
        self.calls=0;self.requests=0;self.max_requests=max_requests;self.lock=RLock()
        def reserve_attempt():
            if self.calls>=max_model_calls:raise RuntimeError('Session model-call budget exhausted')
            if self.attempt_budget is not None:self.attempt_budget.reserve()
            self.calls+=1
        def bounded(*args):
            reserve_attempt()
            return worker(*args)
        self._attempts=[]
        if (fallback_worker is None)!=(fallback_revision is None):
            raise ValueError('Fallback worker and revision must be supplied together')
        if fallback_worker is not None:
            if not callable(fallback_worker) or not callable(fallback_revision):
                raise ValueError('Trusted fallback worker and revision required')
            def policy_revision():
                values=[revision(),fallback_revision()]
                if any(type(v) is not str or not v.strip() or len(v.encode())>4096 for v in values):
                    raise ValueError('Bounded worker revisions required')
                return POLICY+':'+hashlib.sha256(json.dumps(values).encode()).hexdigest()
            def invoke(role,question,fields,source_id,text):
                reserve_attempt()
                event=dict(call=self.calls,role=role,source_id=source_id,status='started',usage={})
                self._attempts.append(event)
                target=worker if role=='primary' else fallback_worker
                try:result=target(question,fields,source_id,text)
                except Exception as exc:
                    event.update(status='error',error=type(exc).__name__+': '+str(exc)[:512])
                    raise
                # Bounded accounting metadata, not source text or raw responses.
                usage=result.get('usage') if type(result) is dict else None
                if type(usage) is dict:
                    for key in ('model','model_digest','model_calls','input_tokens','output_tokens'):
                        value=usage.get(key)
                        if type(value) is int or value is None:event['usage'][key]=value
                        elif type(value) is str:event['usage'][key]=value[:256]
                return result,event
            extractor=lambda *args:checked_fallback(invoke,*args)
            cache_revision=policy_revision
        else:
            extractor=bounded;cache_revision=revision
        self.cache=ExtractionCache(extractor,cache_revision,max_entries=8)
        self.agent=EvidenceAgent(self.adapter,self.cache)

    def attempts(self):
        """Copy of bounded fallback attempt accounting, including failed attempts."""
        with self.lock:return deepcopy(self._attempts)

    def answer(self, question, fields, document_ids, *, quantity_scales=None, host_supersessions=()):
        """Attempt one mission; invalid and failed attempts consume request quota.

        Model invocations are charged before execution; cache hits are free of
        inference charges but still require current source reads. Counts are
        invocations of the injected worker, not an energy measurement.
        """
        with self.lock:
            if self.requests>=self.max_requests:raise RuntimeError('Session request budget exhausted')
            self.requests+=1;before=self.calls
            result=self.agent.answer(question,fields,document_ids,quantity_scales=quantity_scales,
                                     host_supersessions=host_supersessions)
            return dict(result,session=dict(requests=self.requests,model_calls=self.calls-before,
                total_model_calls=self.calls,route_attempts=self.adapter.attempts,
                route_failures=self.adapter.failures,cache=self.cache.stats(),
                controller='classical_last_success'))
