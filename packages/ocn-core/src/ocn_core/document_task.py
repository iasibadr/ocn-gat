"""Explicit documentary completion contract on the existing evidence session.

Textual plausibility, field coverage, host semantic confirmation and permission
to act are separate. This wrapper executes no downstream action. A trusted host
checker may confirm a documentary answer, not certify universal truth.
"""
from copy import deepcopy
import hashlib,json
from threading import Lock
from .document_session import DocumentSession


class DocumentTask:
    def __init__(self,session,*,completion_check=None,checker_id=None):
        if not isinstance(session,DocumentSession):raise ValueError('DocumentSession required')
        if (completion_check is None)!=(checker_id is None):
            raise ValueError('Completion checker and identifier must be supplied together')
        if completion_check is not None and (not callable(completion_check)
            or type(checker_id) is not str or not checker_id.strip() or len(checker_id.encode())>256):
            raise ValueError('Trusted checker and bounded identifier required')
        self.session=session;self.completion_check=completion_check;self.checker_id=checker_id
        self.checks=0;self.lock=Lock()

    def answer(self,question,fields,document_ids,**kwargs):
        if not self.lock.acquire(blocking=False):raise RuntimeError('Documentary task busy')
        try:
            with self.session.lock:
                fields=deepcopy(fields)
                result=self.session.answer(question,fields,document_ids,**kwargs)
                decision=result['decision']
                versions=decision['original']['source_versions']
                ready=decision['ready'];verdict=None;cache_cleared=False
                if ready and self.completion_check is not None:
                    self.checks+=1
                    verdict=self.completion_check(question,deepcopy(fields),deepcopy(result))
                    if verdict is not None and type(verdict) is not bool:
                        raise ValueError('Completion check must return True, False or None')
                    if verdict is False:
                        # The existing cache has a clear-all API, no targeted eviction.
                        # A rejected extraction must not be repeatedly reused as valid.
                        self.session.cache.clear();cache_cleared=True
                    fresh={i:self.session.adapter.read(i) for i in document_ids}
                    if any(d.sha256!=versions[i] for i,d in fresh.items()):
                        raise ValueError('Source changed during completion check')
                    result['source_paths']={i:d.path for i,d in fresh.items()}
                    result['document_bytes_read']+=sum(d.bytes_read for d in fresh.values())
                    result['discovery_entries']+=sum(d.entries_scanned for d in fresh.values())
                blockers={f:list(v['reasons']) for f,v in decision['fields'].items() if not v['ready']}
                status=('insufficient_evidence' if not ready else
                        'completed' if verdict is True else
                        'verification_failed' if verdict is False else 'needs_verification')
                contract=dict(question=question,fields=fields,document_ids=document_ids,source_versions=versions)
                result['completion']=dict(status=status,required_fields=list(fields),blockers=blockers,
                    fields_covered=ready,documentary_task_completed=ready and verdict is True,
                    host_semantic_verdict=verdict,checker_id=self.checker_id,
                    contract_sha256=hashlib.sha256(json.dumps(contract,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                    checker_invocations_total=self.checks,action_authorized=False,
                    scope='Documentary contract and attributed host verdict; no downstream execution or formal truth proof')
                # Candidate fields remain auditable under decision; only confirmed
                # answers are exposed as usable values by this stricter wrapper.
                result['candidate_values']=deepcopy(result['values'])
                if status!='completed':result['values']={};result['abstain']=True
                result['completion']['cache_cleared_after_rejection']=cache_cleared
                result['session']['cache']=self.session.cache.stats()
                return result
        finally:self.lock.release()
