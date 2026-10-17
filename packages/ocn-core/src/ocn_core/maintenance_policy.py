"""Persisted opt-in maintenance authority, bounded cycles, no background worker."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .candidate_evaluation import canonical,validate_suite
from .application import locked,lifecycle
from .model_budget import sync_directory
from .bridge_repair import LocalBridgeRepairer
from .hybrid_repair import hybrid_repair


def authority(config):
    return hashlib.sha256(canonical({k:v for k,v in config.items() if k not in ('integration','evolution')})).hexdigest()


def validate(value):
    fields={'format','authority','contract','suite','designer_model','audit_root','max_cycles','used_cycles','candidate_limit','observe_runtime','share_acceptance_feedback'}
    if type(value) is not dict:raise ValueError('Invalid maintenance policy')
    if value.get('format')=='gat.maintenance.v2':
        fields=fields|{'preserve_acceptance'}
        if type(value.get('preserve_acceptance')) is not bool:raise ValueError('Boolean acceptance preservation required')
    elif value.get('format')!='gat.maintenance.v1':raise ValueError('Invalid maintenance policy')
    if set(value)!=fields:raise ValueError('Invalid maintenance policy')
    for name,limit in (('contract',4096),('designer_model',256)):
        if type(value[name]) is not str or not value[name].strip() or len(value[name].encode())>limit:raise ValueError('Invalid maintenance '+name)
    if type(value['authority']) is not str or len(value['authority'])!=64:raise ValueError('Invalid maintenance authority')
    if type(value['audit_root']) is not str or not Path(value['audit_root']).is_absolute():raise ValueError('Absolute audit directory required')
    if type(value['max_cycles']) is not int or not 1<=value['max_cycles']<=100:raise ValueError('Maintenance cycles must be 1..100')
    if type(value['used_cycles']) is not int or not 0<=value['used_cycles']<=value['max_cycles']:raise ValueError('Invalid consumed cycles')
    if type(value['candidate_limit']) is not int or not 1<=value['candidate_limit']<=8:raise ValueError('Invalid candidate limit')
    if type(value['observe_runtime']) is not bool or type(value['share_acceptance_feedback']) is not bool:raise ValueError('Boolean permissions required')
    validate_suite(value['suite'])


def persist(root,value,*,initial=False):
    validate(value);path=root/'maintenance.json'
    if initial:
        with path.open('x') as handle:
            json.dump(value,handle);handle.flush();os.fsync(handle.fileno())
        sync_directory(root);return
    fd,tmp=tempfile.mkstemp(prefix='.maintenance-',dir=root)
    try:
        with os.fdopen(fd,'w') as handle:
            json.dump(value,handle);handle.flush();os.fsync(handle.fileno())
        os.replace(tmp,path);sync_directory(root)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def read(root):
    from .gat import unique
    fd=os.open(root/'maintenance.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as handle:
        import stat
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):raise ValueError('Regular maintenance policy required')
        raw=handle.read(131073)
    if len(raw)>131072:raise ValueError('Maintenance policy too large')
    value=json.loads(raw,object_pairs_hook=unique);validate(value);return value


def separate_audit(root,config,audit):
    for protected in (root,Path(config['habitat']).resolve()):
        if audit==protected or protected in audit.parents or audit in protected.parents:
            raise ValueError('Maintenance audit must be separate from instance and habitat')


def configure(instance,contract,suite,designer_model,audit_root,max_cycles,*,candidate_limit=8,observe_runtime=False,share_acceptance_feedback=False,preserve_acceptance=False):
    from .gat import load,ISOLATED_FORMAT,BROKERED_FORMAT
    root,config=load(instance);audit=Path(audit_root).resolve()
    with locked(root):
        root,config=load(root)
        if config['format'] not in (ISOLATED_FORMAT,BROKERED_FORMAT):raise ValueError('Maintenance requires isolated execution')
        if observe_runtime and config['format']!=ISOLATED_FORMAT:raise ValueError('Runtime observation requires offline mode')
        if lifecycle(root) not in ('active','paused'):raise RuntimeError('Incomplete instance')
        policy=dict(format='gat.maintenance.v2',authority=authority(config),contract=contract,suite=json.loads(canonical(suite)),
            designer_model=designer_model,audit_root=str(audit),max_cycles=max_cycles,used_cycles=0,candidate_limit=candidate_limit,
            observe_runtime=observe_runtime,share_acceptance_feedback=share_acceptance_feedback,preserve_acceptance=preserve_acceptance)
        validate(policy);separate_audit(root,config,audit)
        kind='response' if config['format']==ISOLATED_FORMAT else 'request'
        if any(set(c['expected'])!={kind} for c in suite['cases']):raise ValueError('Maintenance suite contract mismatch')
        if (root/'maintenance.json').exists():raise FileExistsError('Maintenance policy already configured; budget cannot be reset')
        audit.mkdir(exist_ok=False)
        persist(root,policy,initial=True)
    return status(instance)


def status(instance):
    from .gat import load
    root,config=load(instance)
    with locked(root):
        root,config=load(root);p=read(root)
        return dict(format=p['format'],authority_matches=p['authority']==authority(config),lifecycle=lifecycle(root),
            used_cycles=p['used_cycles'],max_cycles=p['max_cycles'],remaining_cycles=p['max_cycles']-p['used_cycles'],
            preserve_acceptance=p.get('preserve_acceptance',False),
            designer_model=p['designer_model'],candidate_limit=p['candidate_limit'],audit_root=p['audit_root'],
            suite_sha256=hashlib.sha256(canonical(p['suite'])).hexdigest())


@contextmanager
def cycle_lock(root):
    import fcntl
    with (root/'maintenance.lock').open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise RuntimeError('Maintenance cycle already running') from exc
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def tick(instance):
    from .gat import load
    root,config=load(instance)
    with cycle_lock(root):
        with locked(root):
            root,config=load(root);p=read(root)
            if lifecycle(root)!='active':raise RuntimeError('Instance is paused or uninitialized')
            if p['authority']!=authority(config):raise ValueError('Maintenance authority changed')
            audit=Path(p['audit_root']).resolve(strict=True);separate_audit(root,config,audit)
            if p['used_cycles']>=p['max_cycles']:raise RuntimeError('Maintenance cycle budget exhausted')
            p['used_cycles']+=1
            persist(root,p)  # Consume before work; failures and restarts never refund.
        result=hybrid_repair(root,p['contract'],p['suite'],LocalBridgeRepairer(p['designer_model'],proposal_format='lines'),
            audit/('cycle-'+str(p['used_cycles'])),limit=p['candidate_limit'],observe_runtime=p['observe_runtime'],
            share_acceptance_feedback=p['share_acceptance_feedback'],preserve_acceptance=p.get('preserve_acceptance',False))
        return dict(cycle=p['used_cycles'],max_cycles=p['max_cycles'],result=result)
