"""Optional process-local document identity, preserving exact-version admission.

Pinned descriptors distinguish same-content copies during local renames. No
persistent relocation promotion, cross-filesystem migration or restart identity.
"""
from contextlib import contextmanager
from threading import Lock
from .document_adapter import DocumentAdapter,Document

import hashlib,os,re,stat
from pathlib import PurePosixPath

class _LiveFileReference:
    def __init__(self,root,path,digest,*,max_entries=256,max_bytes=65536,max_total_bytes=262144):
        self.root_fd=None;self.fd=None
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('Expected enrolled digest required')
        for n in (max_entries,max_bytes,max_total_bytes):
            if type(n) is not int or n<1:raise ValueError('Positive budgets required')
        self.digest=digest;self.max_entries=max_entries;self.max_bytes=max_bytes
        self.max_total_bytes=max_total_bytes
        try:
            self.root_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            self.fd=self._open(path)
            self.identity=self._identity(self.fd)
            if hashlib.sha256(self._raw(self.fd,{'bytes':0})).hexdigest()!=digest:raise ValueError('Version differs at pin')
        except BaseException:
            self.close();raise

    @staticmethod
    def _identity(fd):
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):raise ValueError('Regular file required')
        if st.st_nlink!=1:raise ValueError('Unlinked or multiply linked file')
        return st.st_dev,st.st_ino

    def _open(self,path,*,directory=False):
        if self.root_fd is None:raise ValueError('Pin is closed')
        if type(path) is not str:raise ValueError('Canonical habitat path required')
        p=PurePosixPath(path)
        if (type(path) is not str or not path or '\\' in path or '\x00' in path
            or p.is_absolute() or '..' in p.parts or p.as_posix()!=path
            or (not directory and p.suffix.lower() not in ('.md','.txt'))):
            raise ValueError('Canonical habitat path required')
        fd=os.dup(self.root_fd)
        try:
            for i,part in enumerate(p.parts):
                flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK
                if directory or i<len(p.parts)-1:flags|=os.O_DIRECTORY
                child=os.open(part,flags,dir_fd=fd);os.close(fd);fd=child
            return fd
        except BaseException:
            os.close(fd);raise

    def _raw(self,fd,budget):
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>self.max_bytes:
            raise ValueError('Read capacity or file type invalid')
        limit=min(self.max_bytes,self.max_total_bytes-budget['bytes'])
        if limit<0:raise ValueError('Document read budget exceeded')
        raw=os.pread(fd,limit+1,0);budget['bytes']+=len(raw)
        if len(raw)>limit:raise ValueError('Document read budget exceeded')
        after=os.fstat(fd)
        fingerprint=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if fingerprint(before)!=fingerprint(after) or len(raw)!=before.st_size:
            raise ValueError('File changed or short read')
        return raw

    def snapshot(self):
        if self.fd is None:raise ValueError('Pin is closed')
        budget={'bytes':0}
        if self._identity(self.fd)!=self.identity or hashlib.sha256(self._raw(self.fd,budget)).hexdigest()!=self.digest:
            raise ValueError('Pinned version changed')
        pending=['.'];matches=[];scanned=0
        while pending:
            directory=pending.pop();fd=self._open(directory,directory=True)
            try:
                with os.scandir(fd) as entries:
                    for entry in entries:
                        scanned+=1
                        if scanned>self.max_entries:raise ValueError('Discovery entry budget exceeded')
                        observed=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                        relative=entry.name if directory=='.' else directory+'/'+entry.name
                        if stat.S_ISDIR(observed.st_mode):pending.append(relative)
                        elif (stat.S_ISREG(observed.st_mode) and PurePosixPath(relative).suffix.lower() in ('.md','.txt')
                            and (observed.st_dev,observed.st_ino)==self.identity):matches.append(relative)
            finally:os.close(fd)
        if len(matches)!=1:raise ValueError('No unique path to pinned file in habitat')
        path=matches[0];candidate=self._open(path)
        try:
            if self._identity(candidate)!=self.identity:raise ValueError('Candidate changed before observation')
            raw=self._raw(candidate,budget)
            if hashlib.sha256(raw).hexdigest()!=self.digest or self._identity(candidate)!=self.identity:
                raise ValueError('Candidate changed before observation')
            observed_stat=os.fstat(candidate)
        finally:os.close(candidate)
        final=self._open(path)
        try:
            stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
            if stamp(os.fstat(final))!=stamp(observed_stat):
                raise ValueError('Candidate path changed after reading')
        finally:os.close(final)
        return dict(path=path,sha256=self.digest,text=raw.decode('utf-8'),
            entries_scanned=scanned,bytes_read=budget['bytes'])

    def close(self):
        for name in ('fd','root_fd'):
            fd=getattr(self,name,None)
            if fd is not None:os.close(fd);setattr(self,name,None)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class LiveDocumentAdapter(DocumentAdapter):
    """Explicitly pin enrolled files before relocation; close or use a context manager.

    Persistent bind/accept_version operations keep the parent host-only contract.
    Changing a binding invalidates its live pin; unpin and pin again explicitly.
    """
    def __init__(self,*args,max_pins=8,**kwargs):
        super().__init__(*args,**kwargs)
        if type(max_pins) is not int or not 1<=max_pins<=128:
            raise ValueError('Live pin capacity must be 1..128')
        self.max_pins=max_pins;self._pins={};self._gate=Lock();self._closed=False
        self._pid=os.getpid()

    @contextmanager
    def _live_guard(self):
        if os.getpid()!=self._pid:raise RuntimeError('Live adapter cannot cross process boundaries')
        if not self._gate.acquire(blocking=False):raise RuntimeError('Live adapter busy')
        try:
            if self._closed:raise ValueError('Live adapter closed')
            yield
        finally:self._gate.release()

    def pin(self,document_id):
        self._id(document_id)
        with self._live_guard(),self._locked():
            if document_id in self._pins:raise ValueError('Document already pinned')
            if len(self._pins)>=self.max_pins:raise ValueError('Live pin capacity exhausted')
            binding=self._load().get(document_id)
            if binding is None:raise ValueError('Unknown document identifier')
            reference=_LiveFileReference(self.root,binding['path'],binding['sha256'],
                max_entries=self.max_entries,max_bytes=self.max_bytes,max_total_bytes=self.max_total_bytes)
            self._pins[document_id]=(reference,dict(binding))

    def unpin(self,document_id):
        with self._live_guard():
            if document_id not in self._pins:raise ValueError('Document not pinned')
            reference,_=self._pins.pop(document_id);reference.close()

    def _check_root(self,reference):
        root=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            current=os.fstat(root);held=os.fstat(reference.root_fd)
            if (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino):
                raise ValueError('Habitat root changed since pin')
        finally:os.close(root)

    def read(self,document_id,*,discovery_bytes=None):
        self._id(document_id)
        if discovery_bytes is not None and (type(discovery_bytes) is not int or discovery_bytes<0):
            raise ValueError('Discovery byte length must be a nonnegative integer')
        with self._live_guard(),self._locked():
            if document_id not in self._pins:raise ValueError('Document must be explicitly pinned')
            reference,binding=self._pins[document_id]
            if self._load().get(document_id)!=binding:raise ValueError('Binding changed since pin')
            # Do not interpret an old relative path against a replaced habitat root.
            self._check_root(reference)
            observed=reference.snapshot()
            self._check_root(reference)
            path=observed['path']
            return Document(document_id,path,observed['sha256'],observed['text'],
                binding['path'] if path!=binding['path'] else None,
                observed['bytes_read'],observed['entries_scanned'])

    def validate_reference(self,document,quote):
        if type(document) is not Document:raise ValueError('Expected document snapshot')
        if type(quote) is not str or not quote.strip():raise ValueError('Nonempty exact quote required')
        if hashlib.sha256(document.text.encode()).hexdigest()!=document.sha256:
            raise ValueError('Snapshot text and digest disagree')
        current=self.read(document.document_id)
        if current.sha256!=document.sha256:raise ValueError('Source changed since snapshot')
        if quote not in current.text:raise ValueError('Quote absent from the current observed version')
        return dict(document_id=document.document_id,path=current.path,sha256=current.sha256,
            quote_sha256=hashlib.sha256(quote.encode()).hexdigest(),bytes_read=current.bytes_read)

    def close(self):
        if not self._gate.acquire(blocking=False):raise RuntimeError('Live adapter busy')
        try:
            for reference,_ in self._pins.values():reference.close()
            self._pins.clear();self._closed=True
        finally:self._gate.release()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
