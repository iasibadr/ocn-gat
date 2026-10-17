"""Bounded host-owned document receipts; unresolved attempts are never replayed.

Uses existing immutable publication, instance locking and request identifiers.
This is not exactly-once external execution or automatic task recovery.
"""
import hashlib,json
from copy import deepcopy
from pathlib import Path
from .application import locked
from .archive_publication import publish
from .model_budget import sync_directory,PersistentAttemptBudget
from .receipt import validate_request_id
from .receipt_archive import read_regular
from .experience_memory import label,ExperienceMemory
from .reward_selection import finite
from .document_session import DocumentSession


def encoded(value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>1048576:raise ValueError('Checkpoint byte limit')
    return raw


class CheckpointedDocumentSession:
    @classmethod
    def create(cls,root,session,*,contract,max_requests=64):
        manifest=cls._manifest(session,contract,max_requests)
        root=Path(root);root.mkdir(mode=0o700,exist_ok=False)
        cls._publish(root/'manifest.json',manifest)
        sync_directory(root.parent)
        return cls(root,session,contract=contract,max_requests=max_requests)

    @staticmethod
    def _manifest(session,contract,max_requests):
        if type(session) is not DocumentSession or type(session.attempt_budget) is not PersistentAttemptBudget:
            raise ValueError('DocumentSession with durable attempt budget required')
        label(contract)
        if type(max_requests) is not int or not 1<=max_requests<=64:raise ValueError('Request bound must be 1..64')
        return dict(format='ocn.document-checkpoint.v1',contract=contract,max_requests=max_requests,
            sources=session.adapter.bindings(),worker_policy=session.cache._revision(),
            budget_root=str(session.attempt_budget.root),budget_limit=session.attempt_budget.limit)

    @staticmethod
    def _publish(path,value):
        raw=encoded(value);publish(path,raw)
        if read_regular(path)!=raw:raise ValueError('Conflicting immutable checkpoint')
        sync_directory(path.parent)

    def __init__(self,root,session,*,contract,max_requests=64):
        root=Path(root)
        if root.is_symlink():raise ValueError('Checkpoint directory symlink forbidden')
        self.root=root.resolve(strict=True);self.session=session
        self.manifest=self._manifest(session,contract,max_requests)
        with locked(self.root):self._check_manifest()

    def _check_manifest(self):
        if read_regular(self.root/'manifest.json')!=encoded(self.manifest):raise ValueError('Checkpoint contract mismatch')
        if self._manifest(self.session,self.manifest['contract'],self.manifest['max_requests'])!=self.manifest:
            raise ValueError('Live session contract changed')

    def _intent(self,request_id,request):
        validate_request_id(request_id)
        if type(request) is not dict:raise ValueError('Document request mapping required')
        raw=encoded(request)
        return dict(request_id=request_id,request_sha256=hashlib.sha256(raw).hexdigest(),
            manifest_sha256=hashlib.sha256(encoded(self.manifest)).hexdigest())

    def recover(self,request_id,request):
        """Historical result only; no source reads, no fresh truth assertion."""
        request=deepcopy(request)
        expected=self._intent(request_id,request)
        with locked(self.root):
            self._check_manifest()
            return self._recover(expected)

    def _recover(self,intent):
        path=self.root/(intent['request_id']+'.intent.json')
        if not path.exists():return dict(state='not_started',historical=True)
        if read_regular(path)!=encoded(intent):raise ValueError('Request identity conflict')
        receipt=self.root/(intent['request_id']+'.result.json')
        if not receipt.exists():return dict(state='unresolved',historical=True)
        value=json.loads(read_regular(receipt))
        if type(value) is not dict or set(value)!={'intent','result'} or value['intent']!=intent:
            raise ValueError('Invalid result receipt')
        return dict(state='completed',historical=True,result=value['result'])

    def _feedback(self,intent,memory,action,context,verdict):
        if type(memory) is not ExperienceMemory:raise ValueError('Existing experience memory required')
        label(action);label(context)
        if type(verdict) is not dict or set(verdict)!={'success','quality','interventions','evidence_id'}:
            raise ValueError('Exact explicit host verdict required')
        if type(verdict['success']) is not bool:raise ValueError('Boolean success required')
        if not 0<=finite(verdict['quality'],'quality')<=1:raise ValueError('Invalid quality')
        if type(verdict['interventions']) is not int or not 0<=verdict['interventions']<=1000000:
            raise ValueError('Invalid intervention count')
        label(verdict['evidence_id'])
        with memory.connect() as db:
            if action not in memory.metadata(db)['actions']:raise ValueError('Unknown feedback action')
        recovered=self._recover(intent)
        if recovered['state']!='completed':raise ValueError('Completed task receipt required for feedback')
        cost=recovered['result']['session']['model_calls']
        if type(cost) is not int or not 0<=cost<=64:raise ValueError('Invalid receipt invocation cost')
        return dict(intent=intent,memory_contract=memory.contract_id,action=action,context=context,
            verdict=verdict,cost=cost)

    @staticmethod
    def _insert_feedback(memory,record):
        verdict=record['verdict']
        inserted=memory.record(event_id=record['intent']['request_id'],context=record['context'],
            action=record['action'],success=verdict['success'],quality=verdict['quality'],
            interventions=verdict['interventions'],cost=record['cost'])
        return dict(state='recorded',inserted=inserted,evidence_id=verdict['evidence_id'],
            estimate=memory.estimate(record['context'],record['action']))

    def record_feedback(self,request_id,request,memory,*,action,context,verdict):
        """Persist explicit host verdict before idempotent experience insertion."""
        intent=self._intent(request_id,deepcopy(request));verdict=deepcopy(verdict)
        with locked(self.root):
            self._check_manifest()
            record=self._feedback(intent,memory,action,context,verdict)
            self._publish(self.root/(request_id+'.feedback.json'),record)
            return self._insert_feedback(memory,record)

    def retry_feedback(self,request_id,request,memory):
        """Replay saved evaluation, never re-evaluate or execute the task."""
        intent=self._intent(request_id,deepcopy(request))
        with locked(self.root):
            self._check_manifest()
            record=json.loads(read_regular(self.root/(request_id+'.feedback.json')))
            if type(record) is not dict or set(record)!={'intent','memory_contract','action','context','verdict','cost'}:
                raise ValueError('Invalid durable feedback record')
            expected=self._feedback(intent,memory,record['action'],record['context'],record['verdict'])
            if record!=expected:raise ValueError('Feedback contract mismatch')
            # Re-establish durable publication after an uncertain prior fsync.
            self._publish(self.root/(request_id+'.feedback.json'),record)
            return self._insert_feedback(memory,record)

    def execute(self,request_id,request):
        request=deepcopy(request)
        intent=self._intent(request_id,request)
        with locked(self.root):
            self._check_manifest()
            old=self._recover(intent)
            if old['state']=='completed':return old
            if old['state']=='unresolved':raise RuntimeError('Unresolved request; automatic replay forbidden')
            if sum(1 for _ in self.root.glob('*.intent.json'))>=self.manifest['max_requests']:
                raise RuntimeError('Persistent request capacity exhausted')
            self._publish(self.root/(request_id+'.intent.json'),intent)
            # Exceptions leave durable unresolved intent. They do not authorize retry.
            result=self.session.answer(**request)
            self._check_manifest()
            self._publish(self.root/(request_id+'.result.json'),dict(intent=intent,result=result))
            return dict(state='completed',historical=False,result=result)
