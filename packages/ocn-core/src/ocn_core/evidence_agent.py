"""Optional structured evidence runtime; no default GAT activation.

An injected extractor remains a trusted integration with unverified semantics.
This runtime enforces coverage, pinned versions and exact conversion contracts.
It does not synthesize unrestricted prose or grant document-defined authority.
"""
from copy import deepcopy
from .document_adapter import DocumentAdapter
from .evidence_coverage import assess_coverage
from .evidence_revisions import assess_revised_coverage
from .quantity_normalization import canonical_quantity


class EvidenceAgent:
    def __init__(self, adapter, extractor, *, max_source_bytes=262144, extract_many=None):
        if not isinstance(adapter, DocumentAdapter) or not callable(extractor):
            raise ValueError('Document adapter and callable extractor required')
        if type(max_source_bytes) is not int or not 1 <= max_source_bytes <= 262144:
            raise ValueError('Invalid source budget')
        self.adapter, self.extractor, self.max_source_bytes = adapter, extractor, max_source_bytes
        if extract_many is not None and not callable(extract_many):
            raise ValueError('Callable extraction organ required')
        self.extract_many = extract_many

    def answer(self, question, fields, document_ids, *, quantity_scales=None, host_supersessions=()):
        if type(question) is not str or not question.strip() or len(question.encode()) > 4096:
            raise ValueError('Bounded question required')
        if (type(fields) is not dict or not fields
                or any(type(v) is not str or not v.strip() or len(v.encode()) > 1024 for v in fields.values())):
            raise ValueError('Explicit field descriptions required')
        fields = deepcopy(fields)
        if (type(document_ids) is not tuple or not 1 <= len(document_ids) <= 8
                or any(type(i) is not str for i in document_ids) or len(set(document_ids)) != len(document_ids)):
            raise ValueError('One to eight distinct document identifiers required')
        # Validate field/source shape before any file read or model invocation.
        assess_coverage(tuple(fields), {i: '' for i in document_ids}, [])
        scales = {} if quantity_scales is None else deepcopy(quantity_scales)
        if type(scales) is not dict or any(field not in fields for field in scales):
            raise ValueError('Quantity scale outside field contract')
        for scale in scales.values():
            if type(scale) is not dict or set(scale) != {'base_unit', 'factors'} or type(scale['base_unit']) is not str:
                raise ValueError('Explicit quantity scale required')
            canonical_quantity('0 '+scale['base_unit'], **scale)
        snapshots = {i: self.adapter.read(i) for i in document_ids}
        sources = {i: d.text for i, d in snapshots.items()}
        if sum(len(v.encode()) for v in sources.values()) > self.max_source_bytes:
            raise ValueError('Source budget exceeded before extraction')
        # Validate host rules against pinned source versions before spending calls.
        assess_revised_coverage(tuple(fields), sources, [], host_supersessions=host_supersessions)
        observations, conversions, usage = [], [], []
        batch = None
        if self.extract_many is not None:
            batch = self.extract_many(question, deepcopy(fields), deepcopy(sources))
            if type(batch) is not dict or set(batch) != set(sources):
                raise ValueError('Extraction organ changed source coverage')
        for ident, text in sources.items():
            envelope = (batch[ident] if batch is not None else
                        self.extractor(question, deepcopy(fields), ident, text))
            if (type(envelope) is not dict or set(envelope) != {'observations', 'usage'}
                    or type(envelope['usage']) is not dict or type(envelope['observations']) is not list):
                raise ValueError('Invalid extraction envelope')
            rows = deepcopy(envelope['observations'])
            assess_coverage(tuple(fields), {ident: text}, rows)
            if {r['field'] for r in rows} != set(fields):
                raise ValueError('Extractor omitted a required field')
            for row in rows:
                if row['field'] in scales and row['status'] == 'value':
                    if row['value'] not in row['quote']:
                        raise ValueError('Raw quantity must occur in quoted evidence')
                    conversion = canonical_quantity(row['value'], **scales[row['field']])
                    conversions.append(dict(source_id=ident, field=row['field'], sha256=row['sha256'], **conversion))
                    row['value'] = conversion['value']
                observations.append(row)
            usage.append(deepcopy(envelope['usage']))
        decision = assess_revised_coverage(tuple(fields), sources, observations,
                                           host_supersessions=host_supersessions)
        fresh = {i: self.adapter.read(i, discovery_bytes=len(snapshots[i].text.encode())) for i in document_ids}
        if any(fresh[i].sha256 != snapshots[i].sha256 for i in document_ids):
            raise ValueError('Source changed during extraction')
        return dict(abstain=not decision['ready'], values=decision['values'], decision=decision,
                    conversions=conversions, source_paths={i: fresh[i].path for i in document_ids},
                    extractor_invocations=len(usage), reported_usage=usage, semantic_verification=False,
                    document_bytes_read=sum(d.bytes_read for d in (*snapshots.values(), *fresh.values())),
                    discovery_entries=sum(d.entries_scanned for d in (*snapshots.values(), *fresh.values())))
