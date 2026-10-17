"""Bounded in-process reuse of structurally checked, semantically unverified extraction.

Fresh source reads and final revalidation remain EvidenceAgent's responsibility.
The host revision callback must identify model, extractor code and policy changes.
A cache hit is not new evidence or learning. No disk persistence or default use.
"""
from collections import OrderedDict
import hashlib
import json
from threading import RLock
from .evidence_coverage import assess_coverage


class ExtractionCache:
    def __init__(self, extractor, revision, *, max_entries=32, max_bytes=262144, max_reuses=8):
        if not callable(extractor) or not callable(revision):
            raise ValueError('Extractor and host revision callback required')
        for value, maximum in ((max_entries,256),(max_bytes,4194304),(max_reuses,1024)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('Invalid cache bound')
        self.extractor, self.revision = extractor, revision
        self.max_entries, self.max_bytes, self.max_reuses = max_entries, max_bytes, max_reuses
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = RLock()
        self.hits = self.misses = self.evictions = 0

    def _revision(self):
        value = self.revision()
        if type(value) is not str or not value.strip() or len(value.encode()) > 4096:
            raise ValueError('Bounded host revision required')
        return value

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def stats(self):
        with self._lock:
            return dict(hits=self.hits,misses=self.misses,evictions=self.evictions,
                        entries=len(self._entries),serialized_bytes=self._bytes,
                        byte_scope='UTF-8 serialized entries plus key bytes; not Python heap size')

    def __call__(self, question, fields, source_id, text):
        if type(question) is not str or not question.strip() or len(question.encode()) > 4096:
            raise ValueError('Bounded question required')
        if (type(fields) is not dict or any(type(v) is not str or not v.strip() or len(v.encode()) > 1024 for v in fields.values())):
            raise ValueError('Explicit field descriptions required')
        assess_coverage(tuple(fields), {source_id:text}, [])
        with self._lock:
            revision = self._revision()
            # Preserve field order: it can affect the extractor's prompt.
            key = hashlib.sha256(json.dumps([revision,question,list(fields.items()),source_id,
                hashlib.sha256(text.encode()).hexdigest()],ensure_ascii=False).encode()).hexdigest()
            if key in self._entries:
                payload, uses = self._entries.pop(key)
                if uses < self.max_reuses:
                    self._entries[key] = (payload, uses+1)
                    self.hits += 1
                    saved = json.loads(payload)
                    return dict(observations=saved['observations'],usage=dict(cache_hit=True,model_calls=0,
                        input_tokens=0,output_tokens=0,reused_usage=saved['usage'],extractor_revision=revision))
                self._bytes -= len(payload)+len(key)
                self.evictions += 1
            self.misses += 1
            result = self.extractor(question,dict(fields),source_id,text)
            if self._revision() != revision:
                raise ValueError('Extractor revision changed during extraction')
            if (type(result) is not dict or set(result) != {'observations','usage'} or type(result['usage']) is not dict):
                raise ValueError('Invalid extraction envelope')
            assess_coverage(tuple(fields), {source_id:text}, result['observations'])
            if {r['field'] for r in result['observations']} != set(fields):
                raise ValueError('Extractor omitted required fields')
            payload = json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
            size = len(payload)+len(key)
            if size <= self.max_bytes:
                while self._entries and (len(self._entries) >= self.max_entries or self._bytes+size > self.max_bytes):
                    old_key,(old_payload,_) = self._entries.popitem(last=False)
                    self._bytes -= len(old_payload)+len(old_key)
                    self.evictions += 1
                self._entries[key] = (payload,0)
                self._bytes += size
            returned = json.loads(payload)
            returned['usage'] = dict(returned['usage'],cache_hit=False,extractor_revision=revision)
            return returned
