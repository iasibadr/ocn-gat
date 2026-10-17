"""Immutable candidate extraction snapshots, revalidated against live documents.

Persistence certifies neither semantics nor truth. A source change invalidates
reuse; an unchanged source may still contain a mistaken model interpretation.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from .grounded_temporal import assess_extraction
from .model_json import parse_model_json
from .temporal_evidence import instant

FORMAT='ocn.temporal-candidates.v1'
MAX_BYTES=262144


def _path(adapter,state):
    path=Path(state).absolute()
    if path.is_symlink():raise ValueError('Memory symlink forbidden')
    path=path.resolve()
    if path==adapter.root or adapter.root in path.parents:
        raise ValueError('Memory must be outside document habitat')
    return path


def capture(adapter,state,extraction,observed_at,*,subject,predicate,expected_source_sha256):
    """Persist one host-requested batch; state must not already exist.

    observed_at maps each enrolled document ID to its host observation time.
    expected_source_sha256 identifies the actual bytes interpreted by the extractor.
    All supplied documents are pinned, including documents with no extracted
    statement. An empty extraction does not certify absence of relevant facts.
    """
    path=_path(adapter,state)
    if type(observed_at) is not dict or not 1<=len(observed_at)<=16:
        raise ValueError('One to sixteen host-observed sources required')
    if type(expected_source_sha256) is not dict or set(expected_source_sha256)!=set(observed_at):
        raise ValueError('Expected digests for exactly the interpreted sources required')
    for digest in expected_source_sha256.values():
        if type(digest) is not str or re.fullmatch('[0-9a-f]{64}',digest) is None:
            raise ValueError('Invalid interpreted source digest')
    for value in observed_at.values():instant(value)
    documents={ident:adapter.read(ident) for ident in observed_at}
    if any(doc.sha256!=expected_source_sha256[ident] for ident,doc in documents.items()):
        raise ValueError('Source version differs from interpreted snapshot')
    sources={ident:dict(text=doc.text,observed_at=observed_at[ident]) for ident,doc in documents.items()}
    cutoff=max(observed_at.values(),key=instant)
    assess_extraction(extraction,sources,subject=subject,predicate=predicate,known_at=cutoff,effective_at=cutoff)
    data=dict(format=FORMAT,subject=subject,predicate=predicate,extraction=extraction,
              sources={ident:dict(sha256=doc.sha256,observed_at=observed_at[ident]) for ident,doc in documents.items()})
    raw=json.dumps(data,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>MAX_BYTES:raise ValueError('Candidate memory budget exceeded')
    # Recheck every source, not only the excerpts the extractor chose to return.
    for ident,doc in documents.items():
        current=adapter.read(ident)
        if current.sha256!=doc.sha256:raise ValueError('Source changed during capture')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.temporal-',delete=False) as stream:
            temporary=Path(stream.name);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        # Atomic creation without replacing an existing batch.
        os.link(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return dict(memory_sha256=hashlib.sha256(raw).hexdigest(),candidate_only=True,semantic_verification=False)


def query(adapter,state,*,expected_sha256,known_at,effective_at):
    """Return a candidate selection only while every pinned version is readable.

    A digest is a host-held integrity reference, not authentication. Exceptions
    indicate invalid state/contracts. Unavailable sources return no candidate.
    Freshness is observational, not a filesystem-wide atomic snapshot.
    """
    instant(known_at);instant(effective_at)
    path=_path(adapter,state)
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Candidate memory budget exceeded')
    digest=hashlib.sha256(raw).hexdigest()
    if type(expected_sha256) is not str or digest!=expected_sha256:raise ValueError('Memory integrity mismatch')
    data=parse_model_json(raw.decode('utf-8'),max_bytes=MAX_BYTES).value
    if set(data)!={'format','subject','predicate','extraction','sources'} or data['format']!=FORMAT:
        raise ValueError('Invalid candidate memory format')
    pins=data['sources']
    if type(pins) is not dict or not 1<=len(pins)<=16:raise ValueError('Invalid source catalogue')
    sources={};provenance=[];unavailable=[]
    for ident,pin in pins.items():
        if type(pin) is not dict or set(pin)!={'sha256','observed_at'}:raise ValueError('Invalid source pin')
        instant(pin['observed_at'])
        try:
            doc=adapter.read(ident)
            if doc.sha256!=pin['sha256']:
                unavailable.append(dict(source_id=ident,reason='version_changed'));continue
            sources[ident]=dict(text=doc.text,observed_at=pin['observed_at'])
            provenance.append(dict(source_id=ident,path=doc.path,sha256=doc.sha256,relocated_from=doc.relocated_from))
        except (OSError,ValueError,RuntimeError) as exc:
            unavailable.append(dict(source_id=ident,reason='source_unavailable',error_type=type(exc).__name__))
    common=dict(memory_sha256=digest,candidate_only=True,semantic_verification=False,provenance=provenance)
    if unavailable:return dict(**common,status='unresolved_provenance',candidate_value=None,unavailable=unavailable)
    result=assess_extraction(data['extraction'],sources,subject=data['subject'],predicate=data['predicate'],
                            known_at=known_at,effective_at=effective_at)
    value=result.pop('value');result.pop('semantic_verification',None)
    return dict(**common,status='candidate_selection',candidate_value=value,assessment=result)
