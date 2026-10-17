"""Explicit GAT structured-document mission on ordinary local instances only."""
import hashlib
from pathlib import Path
from threading import Lock

from .application import locked, lifecycle
from .document_adapter import DocumentAdapter
from .evidence_agent import EvidenceAgent
from .extraction_cache import ExtractionCache
from .extraction_organ import ExtractionOrgan


def run_evidence(instance, fields, *, question=None, quantity_scales=None,
                 mode='serial', max_cells=3, max_model_calls=8, worker=None,
                 persist_memory=False, worker_revision=None):
    # Local import avoids a cycle with the CLI dispatcher.
    from .gat import load, FORMAT
    if mode not in ('serial','organ'):
        raise ValueError('Unknown evidence execution mode')
    if type(max_cells) is not int or not 1 <= max_cells <= 6:
        raise ValueError('One to six cells required')
    if type(max_model_calls) is not int or not 1 <= max_model_calls <= 8:
        raise ValueError('One to eight model calls required')
    if worker is not None and not callable(worker):
        raise ValueError('Callable evidence worker required')
    if type(persist_memory) is not bool:
        raise ValueError('Boolean persistence choice required')
    if persist_memory and worker is not None and (type(worker_revision) is not str or not worker_revision.strip()):
        raise ValueError('Persistent injected worker requires an explicit revision')
    root, config = load(instance)
    with locked(root):
        root, config = load(root)
        if lifecycle(root) != 'active':
            raise RuntimeError('Instance is paused or uninitialized')
        # Do not bypass an adapted bridge, broker call budget, or isolation policy.
        if config['format'] != FORMAT:
            raise ValueError('Evidence execution requires an ordinary local GAT instance')
        if len(config['documents']) > max_model_calls:
            raise ValueError('Call budget cannot cover every source')
        count = 0; count_lock = Lock(); pinned_digest = None
        if worker is None:
            from . import local_evidence
            from .local_models import require_model
            from . import context_budget, model_json
            code_hash = hashlib.sha256(b''.join(Path(m.__file__).read_bytes()
                        for m in (local_evidence, context_budget, model_json))).hexdigest()
            def revision():
                nonlocal pinned_digest
                digest = require_model(config['model'])['digest']
                with count_lock:
                    if pinned_digest is not None and digest != pinned_digest:
                        raise ValueError('Model changed during evidence mission')
                    pinned_digest = digest
                return digest+':'+code_hash
            def engine(*args):
                return local_evidence.extract(*args, model=config['model'])
        else:
            revision = lambda: worker_revision or 'host-injected-worker:ephemeral-session'
            engine = worker
        def bounded(*args):
            nonlocal count
            with count_lock:
                if count >= max_model_calls:
                    raise RuntimeError('Evidence worker budget exhausted')
                count += 1
            return engine(*args)
        persistent = None
        execution = bounded
        if persist_memory:
            from .persistent_extraction import PersistentExtractionCache
            persistent = PersistentExtractionCache(root/'evidence-memory.sqlite', bounded, revision)
            execution = persistent
        if mode == 'organ':
            memory = ExtractionOrgan(execution, revision, max_cells=max_cells)
            batch = memory.extract_many
        else:
            memory = ExtractionCache(execution, revision,
                                     max_entries=8*max_cells, max_bytes=65536*max_cells)
            batch = None
        adapter = DocumentAdapter(config['habitat'], root/'documents.json')
        result = EvidenceAgent(adapter, memory, extract_many=batch).answer(
            config['mission'] if question is None else question, fields, tuple(config['documents']),
            quantity_scales=quantity_scales)
        return dict(format='gat.evidence-run.v1', mode=mode, result=result,
                    worker_calls=count, max_worker_calls=max_model_calls,
                    model=config['model'] if worker is None else None, model_digest=pinned_digest,
                    memory=memory.stats(), memory_scope='instance' if persist_memory else 'this invocation only',
                    persistent_memory=persistent.stats() if persistent else None,
                    adaptation_scope='verified path recovery and source-cell reuse; no learned specialization')
