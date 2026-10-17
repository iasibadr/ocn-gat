"""Pinned trusted Python synthesis bridges; integrity checks are not a sandbox."""
import ast
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

FORMAT = 'gat.python-synthesizer.v1'
MAX_SOURCE_BYTES = 65536


def read_source(path):
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode):raise ValueError('Regular Python source required')
        data=f.read(MAX_SOURCE_BYTES+1)
        after=os.fstat(f.fileno())
    if len(data)>MAX_SOURCE_BYTES:raise ValueError('Integration source too large')
    if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
        raise ValueError('Integration source changed during reading')
    return data


def validate_source(source, entrypoint):
    if type(source) is not bytes or not source or len(source)>MAX_SOURCE_BYTES:
        raise ValueError('Bounded Python source required')
    if type(entrypoint) is not str or not entrypoint.isidentifier() or entrypoint.startswith('_'):
        raise ValueError('Public factory function name required')
    try: tree=ast.parse(source.decode('utf-8'))
    except (SyntaxError,UnicodeError) as exc:raise ValueError('Invalid UTF-8 Python source') from exc
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==entrypoint]
    if len(functions)!=1:raise ValueError('One top-level synchronous factory function required')
    args=functions[0].args
    if (len(args.posonlyargs+args.args)!=1 or args.vararg is not None or args.kwarg is not None
        or args.kwonlyargs or args.defaults):
        raise ValueError('Factory must accept exactly one positional model argument')


def validate_descriptor(value):
    if (type(value) is not dict or set(value)!={'format','sha256','entrypoint'}
        or value['format']!=FORMAT or type(value['sha256']) is not str
        or re.fullmatch('[0-9a-f]{64}',value['sha256']) is None
        or type(value['entrypoint']) is not str or not value['entrypoint'].isidentifier()
        or value['entrypoint'].startswith('_')):
        raise ValueError('Invalid integration descriptor')


@dataclass(frozen=True)
class Integration:
    source: bytes
    entrypoint: str

    def descriptor(self):
        validate_source(self.source,self.entrypoint)
        return dict(format=FORMAT,entrypoint=self.entrypoint,sha256=hashlib.sha256(self.source).hexdigest())

    def write(self, root):
        self.descriptor()
        with (Path(root)/'agent.py').open('xb') as f:
            f.write(self.source);f.flush();os.fsync(f.fileno())


def prepare(path,entrypoint='build_synthesizer'):
    integration=Integration(read_source(path),entrypoint)
    integration.descriptor()  # Parse without importing or executing the module.
    return integration


class PinnedSynthesizer:
    def __init__(self,root,descriptor,model,*,revisioned=False):
        validate_descriptor(descriptor)
        if type(model) is not str or not model.strip():raise ValueError('Model identifier required')
        self.path=(Path(root)/'revisions'/(descriptor['sha256']+'.py') if revisioned else Path(root)/'agent.py')
        self.source=read_source(self.path)
        if hashlib.sha256(self.source).hexdigest()!=descriptor['sha256']:
            raise ValueError('Integration code changed; create a new adapted instance')
        validate_source(self.source,descriptor['entrypoint'])
        self.entrypoint=descriptor['entrypoint'];self.model=model

    def __call__(self,question,documents):
        # Execute the checked bytes, never reopen/import a possibly replaced file.
        # DocumentAgent calls this only after source/context validation. This code
        # and its dependencies remain trusted, with the host process's privileges.
        namespace={'__name__':'gat_embedded_agent','__file__':str(self.path)}
        exec(compile(self.source,str(self.path),'exec'),namespace)
        factory=namespace.get(self.entrypoint)
        if not callable(factory):raise ValueError('Integration factory is not callable')
        synthesizer=factory(self.model)
        if not callable(synthesizer):raise ValueError('Integration factory must return a callable')
        return synthesizer(question,documents)
