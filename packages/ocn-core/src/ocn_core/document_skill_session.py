"""Procedural scalar extraction from pinned JSON text documents.

Combines existing relocation and skill-learning APIs. This is not arbitrary prose
synthesis. An external semantic evaluator and identity guard remain necessary.
Freshness is checked after evaluation and before accepting feedback; it is a
point-in-time check, not a filesystem transaction or permanent freshness promise.
Single in-process owner, no persistent restart or new permission authority.
skill_kind='mass' normalizes grams/kilograms; 'text' learns exact short-string
paths. Each session must retain one field objective and evaluator contract.
"""
import json
from copy import deepcopy
from threading import Lock
from .document_adapter import DocumentAdapter
from .skill_session import SkillSession


def unique_object(pairs):
    result=dict(pairs)
    if len(result)!=len(pairs):raise ValueError('Duplicate document keys')
    return result


class DocumentSkillSession:
    def __init__(self, adapter, worker, evaluate, *, identity_guard, max_requests=64,
                 max_worker_calls=32, capacity=2, adapt_schema_changes=False,
                 delegate_unsupported_shapes=False, skill_kind='mass', retry_rejected_skill=False):
        if not isinstance(adapter,DocumentAdapter) or not callable(evaluate):
            raise ValueError('Document adapter and trusted evaluator required')
        if not callable(identity_guard):raise ValueError('Trusted identity guard required')
        self.adapter=adapter;self.lock=Lock();self.active=None;self.verified_source=None
        self.requests=0;self.max_requests=max_requests
        def checked_evaluate(c,r,record,identity,output):
            verdict=evaluate(c,r,record,identity,output)
            document=self.active
            fresh=self.adapter.read(document.document_id)
            if fresh.sha256!=document.sha256:
                raise ValueError('Document version changed during evaluation')
            self.verified_source=dict(document_id=fresh.document_id,path=fresh.path,
                                      sha256=fresh.sha256,bytes_read=fresh.bytes_read)
            return verdict
        self.identity_guard=identity_guard
        self.skills=SkillSession(worker,checked_evaluate,capacity=capacity,
            max_requests=max_requests,max_worker_calls=max_worker_calls,
            learn_from_feedback=True,adapt_schema_changes=adapt_schema_changes,
            identity_guard=identity_guard,delegate_unsupported_shapes=delegate_unsupported_shapes,
            skill_kind=skill_kind,retry_rejected_skill=retry_rejected_skill)

    def permit(self, connector, revision):
        if not self.lock.acquire(blocking=False):raise RuntimeError('Document skill session busy')
        try:self.skills.permit(connector,revision)
        finally:self.lock.release()

    def answer(self, document_id, *, connector, revision, identity, allowance,
               acquisition_cost, application_cost, delegation_cost):
        if not self.lock.acquire(blocking=False):raise RuntimeError('Document skill session busy')
        try:
            if self.requests>=self.max_requests:raise RuntimeError('Document request budget exhausted')
            self.requests+=1
            if self.skills.permissions.get(connector)!=revision:
                raise ValueError('Revision outside host authority')
            document=self.adapter.read(document_id)
            record=json.loads(document.text,object_pairs_hook=unique_object)
            if type(record) is not dict:raise ValueError('JSON object document required')
            if self.identity_guard(connector,revision,deepcopy(record),identity) is not True:
                raise ValueError('Host envelope identity rejected')
            self.active=document;self.verified_source=None
            result=self.skills.run(connector,revision,record,identity,allowance=allowance,
                acquisition_cost=acquisition_cost,application_cost=application_cost,
                delegation_cost=delegation_cost)
            return dict(result,source=dict(self.verified_source),
                        initial_read_bytes=document.bytes_read,
                        initial_entries_scanned=document.entries_scanned)
        finally:
            self.active=None;self.verified_source=None;self.lock.release()
