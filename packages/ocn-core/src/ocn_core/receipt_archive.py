"""Explicit archive-before-removal of evaluated receipts on a trusted host."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from .application import locked
from .experience_memory import ExperienceMemory
from .model_budget import sync_directory


def read_regular(path,limit=1048576):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Regular archive/receipt file required')
        raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('Archive/receipt too large')
        os.fsync(stream.fileno())
    return raw


def archive_receipts(instance,reservoir,*,limit=64):
    from .gat import load,unique
    from .maintenance_policy import separate_audit
    if type(limit) is not int or not 1<=limit<=256:raise ValueError('Archive batch must be 1..256')
    target=Path(reservoir).absolute()
    if target.is_symlink():raise ValueError('Reservoir symlink forbidden')
    target=target.resolve(strict=True)
    if not target.is_dir():raise ValueError('Existing reservoir directory required')
    root,_=load(instance)
    with locked(root):
        root,config=load(root);separate_audit(root,config,target)
        return _archive_locked(root,target,limit=limit)


def _archive_locked(root,target,*,limit=64):
    """Caller owns instance lock and validates external target and batch limit."""
    from .gat import unique
    memories=root/'feedback-memory';receipts=root/'run-receipts'
    if memories.is_symlink() or receipts.is_symlink():raise ValueError('Instance data symlinks forbidden')
    stores=sorted(memories.glob('*.sqlite'))
    if len(stores)>64:raise ValueError('Feedback store capacity exceeded')
    evaluated=set()
    for store in stores:
        if re.fullmatch('[0-9a-f]{64}',store.stem) is None:raise ValueError('Unexpected feedback store')
        memory=ExperienceMemory(store,contract_id=store.stem)
        with memory.connect() as db:
            evaluated.update(row[0] for row in db.execute('SELECT event_id FROM outcomes'))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='retired' AND type='table'").fetchone():
                evaluated.update(row[0] for row in db.execute('SELECT event_id FROM retired'))
    chosen=[]
    for path in sorted(receipts.glob('*.json')):
        if len(chosen)>=limit:break
        if re.fullmatch('[0-9a-f]{32}',path.stem) is None:raise ValueError('Unexpected receipt filename')
        if path.stem not in evaluated:continue
        raw=read_regular(path,65536);value=json.loads(raw,object_pairs_hook=unique)
        if value.get('format')!='gat.run-receipt.v1' or value.get('run_id')!=path.stem:raise ValueError('Invalid receipt')
        chosen.append((path,raw))
    if not chosen:return dict(archived=0,archive=None)
    payload=dict(format='gat.receipt-archive.v1',receipts=[dict(filename=p.name,raw=raw.decode('utf-8')) for p,raw in chosen])
    raw=json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()
    if len(raw)>1048576:raise ValueError('Receipt archive batch too large')
    sha=hashlib.sha256(raw).hexdigest();archive=target/(sha+'.json')
    from .archive_publication import publish
    publish(archive,raw)
    if read_regular(archive)!=raw:raise ValueError('Receipt archive verification failed')
    sync_directory(target)
    # Partial interruption is safe for content: every selected byte is already
    # in the verified archive. Removal is not an all-or-nothing transaction.
    for path,original in chosen:
        if read_regular(path,65536)!=original:raise ValueError('Receipt changed before removal')
        path.unlink()
    sync_directory(receipts)
    return dict(archived=len(chosen),archive=str(archive),sha256=sha,
                feedback_changed=False,unevaluated_receipts_removed=False)
