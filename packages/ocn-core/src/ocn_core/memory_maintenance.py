"""Opt-in bounded memory housekeeping before recorded runs; no worker/LLM."""
import json
import os
from pathlib import Path
import re
import tempfile
from .application import locked, lifecycle
from .experience_memory import ExperienceMemory
from .maintenance_policy import authority, separate_audit
from .model_budget import sync_directory
from .receipt_archive import read_regular, _archive_locked

NAME='memory-maintenance.json'


def validate(p):
    if (type(p) is not dict or set(p)!={'format','authority','reservoir','max_cycles','used_cycles','enabled'}
            or p['format']!='gat.memory-maintenance.v1'):
        raise ValueError('Invalid memory maintenance policy')
    if type(p['authority']) is not str or re.fullmatch('[0-9a-f]{64}',p['authority']) is None:
        raise ValueError('Invalid memory authority')
    if type(p['reservoir']) is not str or not Path(p['reservoir']).is_absolute():
        raise ValueError('Absolute reservoir required')
    if type(p['max_cycles']) is not int or not 1<=p['max_cycles']<=100:
        raise ValueError('Memory cycles must be 1..100')
    if type(p['used_cycles']) is not int or not 0<=p['used_cycles']<=p['max_cycles']:
        raise ValueError('Invalid consumed memory cycles')
    if type(p['enabled']) is not bool:raise ValueError('Boolean permission required')


def read(root):
    from .gat import unique
    p=json.loads(read_regular(root/NAME,4096),object_pairs_hook=unique)
    validate(p);return p


def persist(root,p,*,initial=False):
    validate(p)
    if initial:
        with (root/NAME).open('x') as f:
            json.dump(p,f);f.flush();os.fsync(f.fileno())
        sync_directory(root);return
    fd,tmp=tempfile.mkstemp(prefix='.memory-maintenance-',dir=root)
    try:
        with os.fdopen(fd,'w') as f:json.dump(p,f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,root/NAME);sync_directory(root)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def target(root,config,path):
    p=Path(path).absolute()
    if p.is_symlink():raise ValueError('Reservoir symlink forbidden')
    p=p.resolve(strict=True)
    if not p.is_dir():raise ValueError('Existing reservoir required')
    separate_audit(root,config,p);return p


def configure(instance,reservoir,max_cycles):
    from .gat import load
    root,_=load(instance)
    with locked(root):
        root,config=load(root)
        if lifecycle(root) not in ('active','paused'):raise RuntimeError('Incomplete instance')
        directory=target(root,config,reservoir)
        p=dict(format='gat.memory-maintenance.v1',authority=authority(config),reservoir=str(directory),
               max_cycles=max_cycles,used_cycles=0,enabled=True)
        persist(root,p,initial=True)
    return p


def status(instance,*,disable=False):
    from .gat import load
    root,_=load(instance)
    with locked(root):
        root,config=load(root);p=read(root)
        if disable:p['enabled']=False;persist(root,p)
        return dict(**p,authority_matches=p['authority']==authority(config),lifecycle=lifecycle(root))


def before_run_locked(root,config):
    """Called under GAT's instance lock after its active-state check."""
    path=root/NAME
    if not path.exists() and not path.is_symlink():return
    p=read(root)
    if not p['enabled']:return
    if lifecycle(root)!='active':raise RuntimeError('Instance must be active')
    if p['authority']!=authority(config):raise ValueError('Memory maintenance authority changed')
    directory=target(root,config,p['reservoir'])
    memories=root/'feedback-memory';receipts=root/'run-receipts'
    if memories.is_symlink() or receipts.is_symlink():raise ValueError('Instance data symlinks forbidden')
    stores=sorted(memories.glob('*.sqlite'))
    if len(stores)>64:raise ValueError('Feedback store capacity exceeded')
    loaded=[];pressure=False
    for store in stores:
        if re.fullmatch('[0-9a-f]{64}',store.stem) is None:raise ValueError('Unexpected feedback store')
        memory=ExperienceMemory(store,contract_id=store.stem)
        with memory.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0]
        pressure=pressure or count>=192
        loaded.append(memory)
    receipt_pressure=receipts.exists() and sum(1 for _ in receipts.iterdir())>=160
    if not pressure and not receipt_pressure:return
    if p['used_cycles']>=p['max_cycles']:raise RuntimeError('Memory maintenance budget exhausted')
    # Known external saturation is not an attempted retirement. Keep the
    # authorization available for a later retry after externally freed capacity.
    from .archive_publication import require_capacity
    require_capacity(directory)
    p['used_cycles']+=1
    persist(root,p)  # Consume before any retirement; failures do not refund.
    for memory in loaded:memory.retire(directory,keep_per_pair=32,limit=256)
    _archive_locked(root,directory,limit=64)
    # A pressured store can contain too many distinct contexts to retire any.
    # Do not invoke a model when the same storage pressure remains unresolved.
    for memory in loaded:
        with memory.connect() as db:
            if db.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0]>=192:
                raise RuntimeError('Feedback pressure unresolved after maintenance')
    if receipts.exists() and sum(1 for _ in receipts.iterdir())>=160:
        raise RuntimeError('Receipt pressure unresolved after maintenance')
