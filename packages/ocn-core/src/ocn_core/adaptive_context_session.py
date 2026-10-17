"""Optional local-worker routing after a pre-inference context capacity refusal.

No retries for semantic, source, network, model-output or model-budget failures.
The full and lexical sessions share the same worker's global model-call budget.
"""
from copy import deepcopy
from threading import Lock
from .evidence_context_session import EvidenceContextSession
from .lexical_context import LexicalContextSelector
from .local_evidence_context import LocalEvidenceContextWorker
from .budgeted_evidence import plan
from .source_windows import select_windows

class _CapacityRefusal(ValueError):
    pass

class AdaptiveContextSession:
    def __init__(self,adapter,worker,*,max_requests=8,selection="lexical",max_paragraphs=256):
        if not isinstance(worker,LocalEvidenceContextWorker):
            raise ValueError('Bounded local evidence worker required')
        if type(max_requests) is not int or not 1<=max_requests<=64:
            raise ValueError('Adaptive request limit must be 1..64')
        if selection not in ('lexical','budgeted','source-windows'):
            raise ValueError('Selection must be lexical, budgeted or source-windows')
        self._selection=selection;self._coverage=None
        self._worker=worker;self._limit=max_requests;self._requests=0
        self._lock=Lock();self._last=None
        selector=LexicalContextSelector(True,True)
        self._full=EvidenceContextSession(adapter,self._full_answer,
            (lambda:worker.revision()+':source-windows-v1') if selection=='source-windows' else worker.revision,
            max_requests=max_requests,max_callbacks=max_requests,max_paragraphs=max_paragraphs,
            normalize_unknown_references=selection=='source-windows')
        if selection=='lexical':
            self._lexical=EvidenceContextSession(adapter,worker.answer,
                lambda:worker.revision()+':'+selector.revision()+':adaptive-context-v1',
                selector=selector,max_requests=max_requests,max_callbacks=2*max_requests,
                max_paragraphs=max_paragraphs)
        elif selection=='budgeted':
            self._lexical=EvidenceContextSession(adapter,worker.answer,
                lambda:worker.revision()+':budgeted-evidence-v1:single-batch',
                selector=self._budgeted_select,max_requests=max_requests,
                max_callbacks=2*max_requests,max_paragraphs=max_paragraphs,
                max_selected_paragraphs=2048,cache_capacity=0)
        else:
            self._lexical=EvidenceContextSession(adapter,worker.answer,
                lambda:worker.revision()+':source-windows-v1',selector=self._window_select,
                max_requests=max_requests,max_callbacks=2*max_requests,max_paragraphs=max_paragraphs,
                max_selected_paragraphs=2048,cache_capacity=0,passage_mode='sentence',
                normalize_unknown_references=True)

    def _window_select(self,payload):
        selection,self._coverage=select_windows(payload)
        selected=set(self._coverage['selected_ids'])
        self._worker.context_plan(dict(payload,paragraphs=[p for p in payload['paragraphs'] if p['id'] in selected]))
        self._coverage['fits']=True
        return selection

    def _budgeted_select(self,payload):
        def fits(request):
            try:self._worker.context_plan(request);return True
            except ValueError as exc:
                if str(exc)=='Prompt exceeds maximum conservative context allowance':return False
                raise
        self._coverage=plan(payload,fits,max_batches=1)
        if not self._coverage['all_candidates_packed']:
            raise ValueError('Candidate evidence exceeds single-answer capacity; batching required')
        # All fields receive the union; the worker sees the original source order.
        ids=[i for batch in self._coverage['batches'] for i in batch]
        return {field:list(ids) for field in payload['fields']}

    def _full_answer(self,payload):
        before=self._worker.calls
        try:return self._worker.answer(payload)
        except ValueError as exc:
            if (str(exc)=='Prompt exceeds maximum conservative context allowance'
                and self._worker.calls==before):
                raise _CapacityRefusal('Full context refused before inference') from exc
            raise

    def last_attempt(self):
        """Last bounded routing trace, including failures; no document text stored."""
        return deepcopy(self._last)

    def answer(self,question,fields,document_ids):
        if not self._lock.acquire(blocking=False):raise RuntimeError('Adaptive session busy')
        try:
            if self._requests>=self._limit:raise RuntimeError('Adaptive request budget exhausted')
            self._requests+=1;before=self._worker.calls;self._coverage=None
            self._last=dict(request=self._requests,routes=['full'],fallback_reason=None,
                model_calls=0,status='running')
            try:
                try:receipt=self._full.answer(question,fields,document_ids)
                except _CapacityRefusal:
                    self._last['fallback_reason']='full_context_capacity_before_inference'
                    self._last['routes'].append({'budgeted':'budgeted-coverage','lexical':'unique-coverage','source-windows':'source-windows'}[self._selection])
                    receipt=self._lexical.answer(question,fields,document_ids)
            except Exception as exc:
                self._last.update(status='failed',error_type=type(exc).__name__)
                raise
            else:
                self._last['status']='returned'
                # Routing is capacity adaptation, never a semantic verification.
                result=dict(receipt,context_routing=self._last)
            finally:
                self._last['model_calls']=self._worker.calls-before
                if self._coverage is not None:self._last['coverage']=deepcopy(self._coverage)
            return deepcopy(result)
        finally:self._lock.release()
