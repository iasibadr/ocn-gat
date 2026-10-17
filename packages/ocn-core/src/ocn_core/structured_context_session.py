"""Opt-in bounded fact/condition/exception answers with separate retrieval fields.

This is a classical representation strategy, not a semantic validator, learned
memory, quaternion policy, or permission to act. Original passages are retained.
"""
from copy import deepcopy
from threading import Lock
from .document_adapter import DocumentAdapter
from .evidence_context_session import EvidenceContextSession, _text
from .local_evidence_context import LocalEvidenceContextWorker
from .source_windows import select_windows

_CAPACITY = 'Prompt exceeds maximum conservative context allowance'
_SUFFIXES = ('value', 'conditions', 'exceptions')


def _expand(fields):
    if type(fields) is not dict or not 1 <= len(fields) <= 2:
        raise ValueError('One or two original fields required')
    result = {}
    for index, (name, description) in enumerate(fields.items()):
        _text(name, 128, 'field name')
        _text(description, 1024, 'field description')
        result[f'f{index}_value'] = description + ' — fait principal ou état actuel demandé'
        result[f'f{index}_conditions'] = 'Pour ce champ : ' + description + '. Conditions, réserves et prérequis explicitement établis ; inconnu si non établis. Ne pas inventer une condition.'
        result[f'f{index}_exceptions'] = 'Pour ce champ : ' + description + '. Exceptions et catégories auxquelles les conditions ne s’appliquent pas, explicitement établies ; inconnu si non établies.'
    for description in result.values():
        _text(description, 1024, 'expanded field description')
    return result


def _compose(receipt, fields):
    # Called only with an EvidenceContextSession-validated receipt.
    result = deepcopy(receipt)
    slots = result.pop('fields')
    result['slot_fields'] = slots
    result['slot_selection'] = result.pop('selection')
    result['slot_withheld_text_fields'] = result.pop('withheld_text_fields')
    result['slot_withheld_unknown_references'] = result.pop('withheld_unknown_references')
    result['fields'] = {}
    result['slot_map'] = {}
    for index, name in enumerate(fields):
        mapping = {suffix: f'f{index}_{suffix}' for suffix in _SUFFIXES}
        result['slot_map'][name] = mapping
        parts = [slots[mapping[suffix]] for suffix in _SUFFIXES]
        conflicts = [part for part in parts if part['status'] == 'conflicting']
        if conflicts:
            refs = list(dict.fromkeys(ref for part in conflicts for ref in part['references']))
            value = dict(status='conflicting', answer=None, references=refs)
        elif parts[0]['status'] != 'supported':
            value = deepcopy(parts[0])
        else:
            answer = parts[0]['answer']
            refs = list(parts[0]['references'])
            for label, part in zip(('Conditions', 'Exceptions'), parts[1:]):
                if part['status'] == 'supported':
                    answer += ' ' + label + ' : ' + part['answer']
                    refs.extend(part['references'])
            value = dict(status='supported', answer=answer, references=list(dict.fromkeys(refs)))
        if len(value['references']) > 8 or len((value['answer'] or '').encode()) > 2048:
            raise ValueError('Combined field exceeds receipt bounds')
        result['fields'][name] = value
    result.update(composition='verbatim_slots_v1', retrieval_fields=deepcopy(fields),
                  completeness_verified=False, semantic_verification=False,
                  action_authorized=False)
    return result


class _CapacityRefusal(ValueError):
    pass


class StructuredContextSession:
    """One/two original fields, one shared bounded worker, no result cache.

    Attempts including invalid requests consume the session request budget.
    Calls on the same session must not overlap; busy calls fail immediately.
    """
    def __init__(self, adapter, worker, *, max_requests=8, max_paragraphs=256,
                 max_source_bytes=65536):
        if not isinstance(adapter, DocumentAdapter) or not isinstance(worker, LocalEvidenceContextWorker):
            raise ValueError('Document adapter and bounded local evidence worker required')
        if type(max_requests) is not int or not 1 <= max_requests <= 64:
            raise ValueError('Structured request limit must be 1..64')
        self._worker = worker
        self._limit = max_requests
        self._requests = 0
        self._lock = Lock()
        self._last = None
        self._retrieval_fields = None
        self._coverage = None
        options = dict(max_requests=max_requests, max_paragraphs=max_paragraphs,
                       max_source_bytes=max_source_bytes, cache_capacity=0,
                       normalize_unknown_references=True)
        revision = lambda: worker.revision() + ':structured-context-v1:original-retrieval'
        self._full = EvidenceContextSession(adapter, self._full_answer, revision,
                                            max_callbacks=max_requests, **options)
        self._windows = EvidenceContextSession(adapter, worker.answer, revision,
            selector=self._select, max_callbacks=2 * max_requests,
            passage_mode='sentence', max_selected_paragraphs=2048, **options)

    def _full_answer(self, payload):
        before = self._worker.calls
        try:
            return self._worker.answer(payload)
        except ValueError as exc:
            if str(exc) == _CAPACITY and self._worker.calls == before:
                raise _CapacityRefusal('Full context refused before inference') from exc
            raise

    def _select(self, payload):
        selection, self._coverage = select_windows(dict(payload, fields=self._retrieval_fields))
        selected = {ref for refs in selection.values() for ref in refs}
        paragraphs = [p for p in payload['paragraphs'] if p['id'] in selected]
        self._worker.context_plan(dict(payload, paragraphs=paragraphs))
        self._coverage['fits'] = True
        return {field: [p['id'] for p in paragraphs] for field in payload['fields']}

    def last_attempt(self):
        """Detached routing trace; original field descriptions are not retained."""
        return deepcopy(self._last)

    def answer(self, question, fields, document_ids):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('Structured session busy')
        try:
            if self._requests >= self._limit:
                raise RuntimeError('Structured request budget exhausted')
            self._requests += 1
            before = self._worker.calls
            self._coverage = None
            self._last = dict(request=self._requests, routes=[], fallback_reason=None,
                              model_calls=0, status='running')
            try:
                _text(question, 4096, 'question')
                expanded = _expand(fields)
                self._retrieval_fields = deepcopy(fields)
                if type(document_ids) is not tuple or not 1 <= len(document_ids) <= 8:
                    raise ValueError('One to eight document IDs required')
                for ident in document_ids:
                    _text(ident, 128, 'document ID')
                if len(set(document_ids)) != len(document_ids):
                    raise ValueError('Distinct document IDs required')
                self._last['routes'].append('full')
                try:
                    receipt = self._full.answer(question, expanded, document_ids)
                except _CapacityRefusal:
                    self._last['fallback_reason'] = 'full_context_capacity_before_inference'
                    self._last['routes'].append('source-windows')
                    receipt = self._windows.answer(question, expanded, document_ids)
                result = _compose(receipt, self._retrieval_fields)
                self._last['status'] = 'returned'
            except Exception as exc:
                self._last.update(status='failed', error_type=type(exc).__name__)
                raise
            finally:
                self._last['model_calls'] = self._worker.calls - before
                if self._coverage is not None:
                    self._last['coverage'] = deepcopy(self._coverage)
                self._retrieval_fields = None
            result['context_routing'] = self.last_attempt()
            return result
        finally:
            self._lock.release()
