"""Host-owned persistent attempt budget; callers hold the instance lock."""
import json
import os
from pathlib import Path
import tempfile


def validate_limit(limit):
    if type(limit) is not int or not 1<=limit<=10000:
        raise ValueError('Model call budget must be between 1 and 10000')


def initialize(root,limit):
    validate_limit(limit)
    with (Path(root)/'model-budget.json').open('x') as handle:
        json.dump(dict(limit=limit,used=0),handle);handle.flush();os.fsync(handle.fileno())
    sync_directory(root)


def sync_directory(root):
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def read(root,limit):
    validate_limit(limit)
    fd=os.open(Path(root)/'model-budget.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as handle:
        import stat
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):raise ValueError('Regular budget file required')
        raw=handle.read(1025)
    if len(raw)>1024:raise ValueError('Invalid model budget size')
    def unique(pairs):
        result=dict(pairs)
        if len(result)!=len(pairs):raise ValueError('Duplicate budget fields')
        return result
    value=json.loads(raw,object_pairs_hook=unique)
    if (type(value) is not dict or set(value)!={'limit','used'} or type(value['limit']) is not int
        or value['limit']!=limit or type(value['used']) is not int or not 0<=value['used']<=limit):
        raise ValueError('Invalid persistent model budget')
    return value


def reserve(root,limit):
    value=read(root,limit)
    if value['used']>=limit:raise RuntimeError('Persistent model call budget exhausted')
    value['used']+=1
    # A failed/uncertain write never grants permission to invoke the model.
    fd,path=tempfile.mkstemp(prefix='.model-budget-',dir=root)
    try:
        with os.fdopen(fd,'w') as handle:
            json.dump(value,handle);handle.flush();os.fsync(handle.fileno())
        os.replace(path,Path(root)/'model-budget.json');sync_directory(root)
    finally:
        if os.path.exists(path):os.unlink(path)
    return value


class PersistentAttemptBudget:
    """Exclusive, crash-conservative access to the existing budget file format.

    Linux/POSIX, trusted host directory. Reservation happens before inference;
    an interrupted attempt is never refunded automatically. Not a task journal.
    """
    def __init__(self, root, limit):
        validate_limit(limit)
        supplied=Path(root)
        if supplied.is_symlink():raise ValueError('Budget directory symlink forbidden')
        self.root=supplied.resolve(strict=True)
        if not self.root.is_dir():raise ValueError('Existing budget directory required')
        self.limit=limit
        with self._locked():read(self.root,self.limit)

    @classmethod
    def create(cls,root,limit):
        validate_limit(limit)
        supplied=Path(root)
        if supplied.is_symlink():raise ValueError('Budget directory symlink forbidden')
        resolved=supplied.resolve(strict=True)
        if not resolved.is_dir():raise ValueError('Existing budget directory required')
        # Exclusive initialization refuses any existing budget, even corrupt.
        initialize(resolved,limit)
        return cls(resolved,limit)

    def _locked(self):
        from contextlib import contextmanager
        import fcntl
        import stat
        @contextmanager
        def lock():
            fd=os.open(self.root/'model-budget.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('Regular budget lock required')
                fcntl.flock(fd,fcntl.LOCK_EX)
                yield
            finally:os.close(fd)
        return lock()

    def reserve(self):
        with self._locked():return reserve(self.root,self.limit)

    def snapshot(self):
        with self._locked():return read(self.root,self.limit)
