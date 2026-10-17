"""Read-only local adapter. This is not an operating-system sandbox."""
import json
import math
from pathlib import Path
from .controller import Fault

def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def _finite_float(text):
    value=float(text)
    if not math.isfinite(value):raise ValueError('Nonfinite JSON number')
    return value


def _reject_constant(text):
    raise ValueError('Nonstandard JSON constant')


class DirectoryHabitat:
    def __init__(self, root, dna, max_document_bytes=65536):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Habitat must be a directory')
        if type(max_document_bytes) is not int or max_document_bytes < 1:
            raise ValueError('Invalid document size limit')
        self.dna = dna
        self.limit = max_document_bytes
        self.calls = []
        self.cost = 0

    def charge(self, operation, argument):
        if len(self.calls) >= self.dna.max_calls:
            raise Fault('budget')
        self.calls.append(dict(operation=operation, argument=argument))
        self.cost += 1

    def _load(self, name, metadata=False):
        if type(name) is not str or not name or Path(name).name != name:
            raise Fault('denied')
        if not metadata and name in ('directory.json', 'schemas.json'):
            raise Fault('denied')
        target = self.root / name
        # Reject symlinks, including links within the habitat. No hostile concurrent
        # mutation is supported; an OS sandbox is required for untrusted writers.
        if target.is_symlink():
            raise Fault('denied')
        try:
            with target.open('rb') as handle:
                raw = handle.read(self.limit + 1)
        except FileNotFoundError:
            raise Fault('not_found') from None
        except OSError:
            raise Fault('unavailable') from None
        if len(raw) > self.limit:
            raise Fault('document_too_large')
        try:
            doc = json.loads(raw,object_pairs_hook=_unique_object,
                             parse_float=_finite_float,parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise Fault('invalid_document') from None
        if type(doc) is not dict:
            raise Fault('invalid_document')
        return doc

    def read(self, path):
        self.charge('read', path)
        return self._load(path)

    def locate(self, source):
        self.charge('locate', source)
        if source not in self.dna.source_ids:
            raise Fault('denied')
        path = self._load('directory.json', metadata=True).get(source)
        if type(path) is not str or not path or Path(path).name != path or path in ('directory.json','schemas.json'):
            raise Fault('invalid_directory')
        return path

    def describe(self, source):
        self.charge('describe', source)
        if source not in self.dna.source_ids:
            raise Fault('denied')
        descriptor = self._load('schemas.json', metadata=True).get(source)
        if type(descriptor) is not dict or type(descriptor.get('codec')) is not str:
            raise Fault('invalid_descriptor')
        parts = descriptor.get('value_path')
        if type(parts) is not list or not parts or len(parts) > 16 or any(type(x) is not str for x in parts):
            raise Fault('invalid_descriptor')
        return descriptor
