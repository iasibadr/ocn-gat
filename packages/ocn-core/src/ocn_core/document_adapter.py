"""Bounded exact-version relocation adapter for trusted local text habitats.

Inject `read` into an existing agent's document-reading hook. This is not an
agent converter, semantic verifier, automatic version upgrader or OS sandbox.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


@dataclass(frozen=True)
class Document:
    document_id: str
    path: str
    sha256: str
    text: str
    relocated_from: str | None
    bytes_read: int
    entries_scanned: int


class DocumentAdapter:
    def __init__(self, habitat, state, *, max_bytes=65536, max_total_bytes=262144, max_entries=256, max_documents=128):
        self.root=Path(habitat).resolve(strict=True)
        if not self.root.is_dir():raise ValueError('Document habitat must be a directory')
        self.state=Path(state).absolute()
        if self.state.is_symlink():raise ValueError('State symlink forbidden')
        self.state=self.state.resolve()
        if self.state==self.root or self.root in self.state.parents:raise ValueError('State must be outside document habitat')
        if not self.state.parent.is_dir():raise ValueError('State parent must exist')
        for value in (max_bytes,max_total_bytes,max_entries,max_documents):
            if type(value) is not int or value<1:raise ValueError('Positive integer budgets required')
        self.max_bytes=max_bytes;self.max_total_bytes=max_total_bytes
        self.max_entries=max_entries;self.max_documents=max_documents

    def _path(self, relative):
        if type(relative) is not str or not relative or '\\' in relative or '\x00' in relative:
            raise ValueError('Invalid relative document path')
        p=PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or p.as_posix()!=relative or p.suffix.lower() not in ('.txt','.md'):
            raise ValueError('Only canonical relative .txt/.md paths are supported')
        current=self.root
        for part in p.parts:
            current=current/part
            if current.is_symlink():raise ValueError('Document symlinks forbidden')
        return current

    @contextmanager
    def _locked(self):
        import fcntl
        with self.state.with_suffix(self.state.suffix+'.lock').open('a') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise RuntimeError('Document adapter busy') from exc
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)

    def _load(self):
        if not self.state.exists():return {}
        def unique(pairs):
            value=dict(pairs)
            if len(value)!=len(pairs):raise ValueError('Duplicate state fields')
            return value
        with self.state.open('rb') as f:raw=f.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('State too large')
        data=json.loads(raw,object_pairs_hook=unique)
        if type(data) is not dict or set(data)!={'format','documents'} or data['format'] not in ('ocn.documents.v1','ocn.documents.v2'):raise ValueError('Invalid document state')
        documents=data['documents']
        if type(documents) is not dict or len(documents)>self.max_documents:raise ValueError('Invalid document count')
        for key,value in documents.items():
            self._id(key)
            allowed=({'path','sha256'},) if data['format']=='ocn.documents.v1' else ({'path','sha256'},{'path','sha256','byte_length'})
            if type(value) is not dict or set(value) not in allowed:raise ValueError('Invalid binding')
            if 'byte_length' in value and (type(value['byte_length']) is not int or value['byte_length']<0):
                raise ValueError('Invalid verified byte length')
            self._path(value['path'])
            if type(value['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',value['sha256']) is None:raise ValueError('Invalid digest')
        return documents

    def _save(self,documents):
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',dir=self.state.parent,prefix='.documents-',delete=False) as f:
                temporary=Path(f.name);json.dump(dict(format='ocn.documents.v2',documents=documents),f)
                f.flush();os.fsync(f.fileno())
            os.replace(temporary,self.state)
            fd=os.open(self.state.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if temporary is not None and temporary.exists():temporary.unlink()

    @staticmethod
    def _id(value):
        if type(value) is not str or not value.strip() or len(value)>128:raise ValueError('Invalid document identifier')

    def _read(self,path,budget):
        self._path(path)
        # Bind every intermediate component to a directory descriptor. Checking
        # is_symlink before an absolute open leaves a replacement race: the final
        # O_NOFOLLOW flag alone protects only the leaf, not its parent folders.
        parts=PurePosixPath(path).parts
        directory=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                os.close(directory)
                directory=child
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW,dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd,'rb') as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode):raise ValueError('Only regular document files are supported')
            limit=min(self.max_bytes,self.max_total_bytes-budget['bytes'])
            raw=f.read(limit+1);budget['bytes']+=len(raw)
            after=os.fstat(f.fileno())
        if len(raw)>limit:raise ValueError('Document read budget exceeded')
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('Document changed during reading')
        return hashlib.sha256(raw).hexdigest(),raw.decode('utf-8')

    def bind(self,document_id,path):
        """Host-authorized enrollment of one immutable version; never auto-upgrades."""
        self._id(document_id)
        with self._locked():
            documents=self._load()
            if document_id in documents:raise ValueError('Document already enrolled; no implicit version replacement')
            if len(documents)>=self.max_documents:raise ValueError('Document binding capacity exhausted')
            budget={'bytes':0};digest,text=self._read(path,budget)
            documents[document_id]=dict(path=path,sha256=digest,byte_length=len(text.encode('utf-8')));self._save(documents)
            return Document(document_id,path,digest,text,None,budget['bytes'],0)

    def read(self,document_id, *, discovery_bytes=None):
        """Read the enrolled digest, optionally filtering discovery by byte length.

        A length hint is not an identity or a version authorization. Every returned
        candidate must still match the enrolled digest; the entire eligible tree
        is scanned to reject duplicate copies. A stale/wrong hint may fail closed.
        The current bound path is always checked without the hint. When no hint
        is supplied, reuse a byte length recorded after exact-version verification.
        Legacy bindings acquire this metadata only after a successful read.
        """
        if discovery_bytes is not None and (type(discovery_bytes) is not int or discovery_bytes < 0):
            raise ValueError('Discovery byte length must be a nonnegative integer')
        self._id(document_id)
        with self._locked():
            documents=self._load()
            if document_id not in documents:raise ValueError('Unknown document identifier')
            binding=documents[document_id];old=binding['path'];budget={'bytes':0};scanned=0
            try:
                digest,text=self._read(old,budget)
            except FileNotFoundError:pass
            else:
                if digest==binding['sha256']:
                    size=len(text.encode('utf-8'))
                    if binding.get('byte_length')!=size:
                        # Upgrade only after a successful exact-version observation.
                        binding['byte_length']=size;self._save(documents)
                    return Document(document_id,old,digest,text,None,budget['bytes'],0)
            if discovery_bytes is None:discovery_bytes=binding.get('byte_length')
            matches=[];pending=[self.root]
            while pending:
                directory=pending.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        scanned+=1
                        if scanned>self.max_entries:raise ValueError('Discovery entry budget exceeded')
                        if entry.is_symlink():continue
                        if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path));continue
                        if not entry.is_file(follow_symlinks=False) or Path(entry.name).suffix.lower() not in ('.txt','.md'):continue
                        if discovery_bytes is not None:
                            try:size=entry.stat(follow_symlinks=False).st_size
                            except FileNotFoundError:continue
                            if size!=discovery_bytes:continue
                        relative=Path(entry.path).relative_to(self.root).as_posix()
                        try:digest,text=self._read(relative,budget)
                        except FileNotFoundError:continue
                        if digest==binding['sha256']:matches.append((relative,digest,text))
            if not matches:raise ValueError('Enrolled version unavailable; replacement is not accepted')
            if len(matches)!=1:raise ValueError('Ambiguous relocation; multiple exact copies')
            path,digest,text=matches[0]
            # Re-read before promoting a discovered candidate; report an observed
            # version, never an assurance that the file cannot subsequently change.
            digest_now,text_now=self._read(path,budget)
            if digest_now!=digest:raise ValueError('Candidate changed before promotion')
            documents[document_id]=dict(path=path,sha256=digest,byte_length=len(text.encode('utf-8')));self._save(documents)
            return Document(document_id,path,digest,text_now,old,budget['bytes'],scanned)

    def bindings(self):
        """Return enrolled metadata, not a fresh observation of the source files."""
        with self._locked():
            return self._load()

    def accept_version(self, document_id, path, *, expected_current_sha256, expected_new_sha256):
        """Trusted-host authorized update, never a permission exposed to source text.

        The host supplies the identity link and both version digests. This checks
        content and prevents stale updates; it does not authenticate the host or
        infer that two different texts describe the same logical document.
        """
        self._id(document_id)
        for digest in (expected_current_sha256,expected_new_sha256):
            if type(digest) is not str or re.fullmatch('[0-9a-f]{64}',digest) is None:
                raise ValueError('Explicit version digests required')
        with self._locked():
            documents=self._load()
            if document_id not in documents:raise ValueError('Unknown document identifier')
            old=documents[document_id]
            if old['sha256']!=expected_current_sha256:
                raise ValueError('Version update conflict; current version changed')
            budget={'bytes':0};digest,text=self._read(path,budget)
            if digest!=expected_new_sha256:
                raise ValueError('Candidate does not match authorized version')
            documents[document_id]=dict(path=path,sha256=digest,byte_length=len(text.encode('utf-8')))
            if documents[document_id]!=old:self._save(documents)
            return Document(document_id,path,digest,text,old['path'] if old['path']!=path else None,budget['bytes'],0)

    def validate_reference(self, document, quote):
        """Re-read an observed version before presenting an exact quotation.

        Success checks version membership and exact quote membership, not the
        semantic truth of the answer or permanent filesystem freshness.
        """
        if type(document) is not Document:raise ValueError('Expected document snapshot')
        self._id(document.document_id)
        if type(quote) is not str or not quote.strip():raise ValueError('Nonempty exact quote required')
        if hashlib.sha256(document.text.encode('utf-8')).hexdigest()!=document.sha256:
            raise ValueError('Snapshot text and digest disagree')
        with self._locked():
            documents=self._load();binding=documents.get(document.document_id)
            if binding is None or binding['sha256']!=document.sha256:
                raise ValueError('Snapshot is not the enrolled current version')
            budget={'bytes':0};digest,text=self._read(binding['path'],budget)
            if digest!=document.sha256:raise ValueError('Source changed since snapshot')
            if quote not in text:raise ValueError('Quote absent from the current observed version')
            return dict(document_id=document.document_id,path=binding['path'],sha256=digest,
                        quote_sha256=hashlib.sha256(quote.encode('utf-8')).hexdigest(),bytes_read=budget['bytes'])
