"""Opt-in answer-stage receipts and explicit operator feedback; trusted host."""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from .application import locked
from .experience_memory import ExperienceMemory,label
from .model_budget import sync_directory


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def model_identity(config,model):
    if config['format'] in ('gat.documents.v1','gat.documents.python-brokered.v1'):
        from .local_models import require_model
        value=require_model(model)['digest']
        if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Invalid local model digest')
        return value
    return None  # Arbitrary/offline bridges do not attest which backend they use.


def action_id(config,model,model_digest=None):
    value=dict(format=config['format'],integration=config.get('integration'),model=model)
    if 'synthesis_profile' in config:value['synthesis_profile']=config['synthesis_profile']
    if model_digest is not None:value['model_digest']=model_digest
    return digest(value)


def context_id(config,question,document_versions=None):
    value=dict(question=question,documents=config['documents'])
    if document_versions is not None:
        if (type(document_versions) is not dict or set(document_versions)!=set(config['documents'])
            or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}',v) is None for v in document_versions.values())):
            raise ValueError('Exact enrolled document versions required')
        value.update(scope='document_versions',document_versions=document_versions)
    return digest(value)


def check_broker_models(config,models):
    """Check host catalogue before any receipt preparation or model access."""
    if type(models) not in (list,tuple) or not 1<=len(models)<=8:
        raise ValueError('One to eight authorized models required')
    for model in models:label(model)
    if len(set(models))!=len(models):raise ValueError('Duplicate models')
    allowed=config.get('authorized_models',[config['model']])
    if any(model not in allowed for model in models):
        if 'authorized_models' not in config:raise ValueError('Persistent broker model cannot be overridden')
        raise ValueError('Model outside persistent broker authorization catalogue')


def validate_selection(models,rubric,minimum_observations,reward_weights):
    label(rubric)
    from .reward_selection import finite
    weights=dict(success_weight=1.,quality_weight=0.,intervention_penalty=0.)
    if reward_weights is not None:
        if type(reward_weights) is not dict or set(reward_weights)!=set(weights):
            raise ValueError('Exact success, quality and intervention reward weights required')
        weights=dict(reward_weights)
    for value in weights.values():
        if finite(value,'reward weight')<0:raise ValueError('Nonnegative reward weights required')
    if weights['success_weight']==weights['quality_weight']==0:
        raise ValueError('Positive success or quality reward required')
    if type(models) not in (tuple,list) or not 1<=len(models)<=8:raise ValueError('One to eight authorized models required')
    for name in models:label(name)
    if len(set(models))!=len(models):raise ValueError('Duplicate models')
    if type(minimum_observations) is not int or not 1<=minimum_observations<=32:raise ValueError('Observation minimum must be 1..32')
    return weights


def choose_model(root,config,question,models,rubric,*,minimum_observations=3,reward_weights=None,document_versions=None):
    """Called under the instance lock. Explicit candidate list, no exploration."""
    weights=validate_selection(models,rubric,minimum_observations,reward_weights)
    if config['format']=='gat.documents.python-brokered.v1':check_broker_models(config,models)
    directory=root/'feedback-memory'
    if directory.is_symlink():raise ValueError('Feedback symlink forbidden')
    context=context_id(config,question,document_versions);rows=[];best=None;best_value=0.
    for model in models:
        identity=model_identity(config,model)
        action=action_id(config,model,identity);contract=digest(dict(rubric=rubric,action=action))
        path=directory/(contract+'.sqlite')
        if path.is_symlink():raise ValueError('Memory symlinks forbidden')
        estimate=(ExperienceMemory(path,contract_id=contract).estimate(context,action,**weights) if path.exists()
                  else dict(expected_return=None,observations=0,uncertainty='unknown'))
        eligible=estimate['observations']>=minimum_observations
        rows.append(dict(model=model,model_digest=identity,eligible=eligible,**estimate))
        if eligible and estimate['expected_return']>best_value:
            best=model;best_value=estimate['expected_return']
    if best is None:raise RuntimeError('No sufficiently observed model with positive expected reward')
    return dict(model=best,model_digest=next(r['model_digest'] for r in rows if r['model']==best),
                rubric=rubric,context=context,minimum_observations=minimum_observations,
                criterion=('observed_success_ewma' if weights==dict(success_weight=1.,quality_weight=0.,intervention_penalty=0.)
                           else 'observed_reward_ewma'),reward_weights=weights,
                feedback_scope='mission' if document_versions is None else 'document_versions',
                candidates=rows,uncertainty='uncalibrated')


def prepare(root):
    directory=root/'run-receipts'
    if directory.is_symlink():raise ValueError('Receipt symlink forbidden')
    directory.mkdir(exist_ok=True)
    if sum(1 for _ in directory.iterdir())>=256:raise ValueError('Run receipt capacity exhausted')
    return directory


class RecordedRunError(RuntimeError):
    def __init__(self,receipt):
        self.receipt=receipt
        super().__init__('Recorded run failed; run_id='+receipt['run_id']+'; category='+receipt['error_category'])


def save(directory,config,question,model,result,*,failure=None,model_digest=None,document_versions=None):
    ident=uuid.uuid4().hex
    action=action_id(config,model,model_digest)
    receipt=dict(format='gat.run-receipt.v1',run_id=ident,action=action,
                 context=context_id(config,question,document_versions),
                 feedback_scope='mission' if document_versions is None else 'document_versions',
                 result_sha256=digest(result) if failure is None else None,
                 document_bytes_read=result['document_bytes_read'] if failure is None else None,
                 status='completed' if failure is None else 'failed',model_digest=model_digest)
    if failure is not None:
        # Never store exception messages: provider errors may contain private data.
        receipt['error_category']=('timeout' if isinstance(failure,TimeoutError) else
            'io_error' if isinstance(failure,OSError) else 'validation_error' if isinstance(failure,ValueError)
            else 'execution_error')
    with (directory/(ident+'.json')).open('x') as f:
        json.dump(receipt,f);f.flush();os.fsync(f.fileno())
    sync_directory(directory)
    return receipt


def feedback(instance,run_id,*,rubric,success,quality,interventions):
    from .gat import load,read_json
    label(rubric)
    if type(run_id) is not str or re.fullmatch('[0-9a-f]{32}',run_id) is None:raise ValueError('Invalid run identifier')
    root,_=load(instance)
    with locked(root):
        directory=root/'run-receipts';path=directory/(run_id+'.json')
        if directory.is_symlink() or path.is_symlink():raise ValueError('Receipt symlink forbidden')
        receipt=read_json(path)
        if receipt.get('format')!='gat.run-receipt.v1' or receipt.get('run_id')!=run_id:raise ValueError('Invalid run receipt')
        status=receipt.get('status','completed')  # Existing v1 successful receipts.
        if status not in ('completed','failed'):raise ValueError('Invalid receipt status')
        if status=='failed' and (success is not False or quality!=0):
            raise ValueError('Failed run feedback requires success=no and quality=0')
        action=receipt['action'];context=receipt['context']
        for value in (action,context):
            if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Invalid receipt fingerprint')
        contract=digest(dict(rubric=rubric,action=action))
        memories=root/'feedback-memory'
        if memories.is_symlink():raise ValueError('Feedback symlink forbidden')
        memories.mkdir(exist_ok=True);store=memories/(contract+'.sqlite')
        if store.exists():memory=ExperienceMemory(store,contract_id=contract)
        else:
            if sum(1 for _ in memories.iterdir())>=64:raise ValueError('Feedback contract capacity exhausted')
            memory=ExperienceMemory.create(store,contract_id=contract,actions=[action],capacity=256)
        inserted=memory.record(event_id=run_id,context=context,action=action,success=success,
            quality=quality,interventions=interventions,cost=receipt['document_bytes_read'])
        return dict(run_id=run_id,recorded=inserted,action=action,rubric=rubric,
                    estimate=memory.estimate(context,action),source='explicit_operator_feedback',
                    cost_scope='unknown' if receipt['document_bytes_read'] is None else 'document_reads_only_not_total_cost')


def retire_feedback(instance,action,*,rubric,reservoir,keep_per_pair=32,limit=256):
    """Explicit host operation, separate reservoir, no instance/source deletion."""
    from .gat import load
    from .maintenance_policy import separate_audit
    label(rubric)
    if type(action) is not str or re.fullmatch('[0-9a-f]{64}',action) is None:raise ValueError('Invalid action fingerprint')
    target=Path(reservoir).absolute()
    if target.is_symlink():raise ValueError('Reservoir symlink forbidden')
    target=target.resolve(strict=True)
    root,_=load(instance)
    with locked(root):
        root,config=load(root);separate_audit(root,config,target)
        memories=root/'feedback-memory'
        if memories.is_symlink():raise ValueError('Feedback symlink forbidden')
        contract=digest(dict(rubric=rubric,action=action))
        store=memories/(contract+'.sqlite')
        if not store.is_file():raise ValueError('Existing feedback memory required for retirement')
        memory=ExperienceMemory(store,contract_id=contract)
        result=memory.retire(target,keep_per_pair=keep_per_pair,limit=limit)
        return dict(action=action,rubric=rubric,**result,run_receipts_removed=False)
