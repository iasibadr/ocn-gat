"""Optional bounded source-cell organ over an injected LLM extraction worker.

Cells retain versioned extraction memory; each task recruits the needed source
cells. No model weight changes, autonomous code generation or semantic proof.
The host must supply a thread-safe worker/revision callback. EvidenceAgent remains
responsible for actual source reads and final version checks.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from threading import RLock

from .evidence_coverage import assess_coverage
from .extraction_cache import ExtractionCache


class ExtractionOrgan:
    def __init__(self, worker, revision, *, max_cells=3, entries_per_cell=8,
                 bytes_per_cell=65536, max_reuses=8):
        if type(max_cells) is not int or not 1 <= max_cells <= 6:
            raise ValueError('One to six worker cells required')
        self.cells = tuple(ExtractionCache(worker, revision, max_entries=entries_per_cell,
                          max_bytes=bytes_per_cell, max_reuses=max_reuses) for _ in range(max_cells))
        self._lock = RLock()
        self._batches = 0

    def cell_for(self, source_id):
        if type(source_id) is not str or not source_id.strip():
            raise ValueError('Source identifier required')
        return int.from_bytes(hashlib.sha256(source_id.encode()).digest()[:8], 'big') % len(self.cells)

    def __call__(self, question, fields, source_id, text):
        # Serialize batch admission across callers: the same bound applies globally.
        with self._lock:
            return self.cells[self.cell_for(source_id)](question, fields, source_id, text)

    def extract_many(self, question, fields, sources):
        if type(sources) is not dict or not 1 <= len(sources) <= 8:
            raise ValueError('One to eight sources required')
        if type(question) is not str or not question.strip() or len(question.encode()) > 4096:
            raise ValueError('Bounded question required')
        if (type(fields) is not dict or any(type(v) is not str or not v.strip()
                or len(v.encode()) > 1024 for v in fields.values())):
            raise ValueError('Explicit field descriptions required')
        assess_coverage(tuple(fields), sources, [])
        if sum(len(t.encode()) for t in sources.values()) > 262144:
            raise ValueError('Organ source budget exceeded')
        fields, sources = deepcopy(fields), deepcopy(sources)
        with self._lock:
            self._batches += 1
            with ThreadPoolExecutor(max_workers=min(len(self.cells), len(sources))) as pool:
                futures = {i: pool.submit(self.cells[self.cell_for(i)], question,
                                         deepcopy(fields), i, text) for i, text in sources.items()}
                # Every result stays paired with its source; consumers validate envelopes.
                # The executor joins started workers even on failure, so no background work
                # survives a failed batch. Successful cached subresults may be reused later.
                return {i: future.result() for i, future in futures.items()}

    def clear(self):
        with self._lock:
            for cell in self.cells:
                cell.clear()

    def stats(self):
        with self._lock:
            return dict(max_cells=len(self.cells), batches=self._batches,
                        cells=[cell.stats() for cell in self.cells],
                        semantics='bounded sharded reuse, not learned differentiation')
