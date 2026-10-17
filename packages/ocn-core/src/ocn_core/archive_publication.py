"""Publish complete immutable archive bytes without replacing an existing file.

Trusted local reservoir. Caller verifies bytes and fsyncs the directory before
retiring any source. Crash leftovers are not silently deleted or interpreted.
"""
from itertools import islice
import os
from pathlib import Path
import tempfile


def require_capacity(directory):
    """Observe room for provisional + final entries; not a reservation.

    All visible entries count, including unknown crash leftovers. Concurrent
    writers can change capacity after this check; publish checks again.
    """
    if sum(1 for _ in islice(Path(directory).iterdir(),255))>=255:
        raise ValueError('Reservoir file capacity exhausted')


def publish(path,raw):
    path=Path(path)
    if path.is_symlink():raise ValueError('Archive symlink forbidden')
    if path.exists():return
    # Reserve both the provisional and final entries until unlink completes.
    require_capacity(path.parent)
    fd,name=tempfile.mkstemp(prefix='.archive-pending-',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem hard-link creation publishes a complete inode and is
        # exclusive. A concurrent writer's final file is never overwritten.
        try:os.link(temporary,path,follow_symlinks=False)
        except FileExistsError:pass  # Caller must verify the winning bytes.
    finally:
        temporary.unlink(missing_ok=True)
