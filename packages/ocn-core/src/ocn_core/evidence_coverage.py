"""Optional structural coverage check for explicit, host-defined answer fields.

This does NOT certify semantic truth or complete extraction. Sources can be
wrong; an extractor can miss a claim or invent a value alongside a real quote.
The caller supplies authorized sources and canonical values. This module never
infers source priority, entity identity, unit conversion, or action permission.
No default DocumentAgent path uses it until extraction has been evaluated.
"""
import hashlib


def assess_coverage(required_fields, sources, observations):
    """Check a bounded source/field matrix and return an auditable decision.

Sources: {source_id: full_text}. Each observation has exactly source_id, field,
sha256, status, value, quote. Status is value/absent/ambiguous. A value needs a
nonempty canonical string and an exact supporting excerpt; ambiguous needs an
excerpt and value=None; absent has value=quote=None and refers to the full source.
Absent is an extractor assertion, never a mechanically proven absence.
Missing cells, ambiguous cells, absent fields and unequal canonical values block
readiness. Every supplied observation is validated even if another blocks output.
"""
    if (type(required_fields) is not tuple or not 1 <= len(required_fields) <= 8
            or any(type(f) is not str or not f.strip() or len(f) > 128 for f in required_fields)
            or len(set(required_fields)) != len(required_fields)):
        raise ValueError('One to eight unique required fields needed')
    if (type(sources) is not dict or not 1 <= len(sources) <= 8
            or any(type(k) is not str or not k.strip() or len(k) > 128
                   or type(v) is not str for k, v in sources.items())):
        raise ValueError('One to eight named text sources needed')
    if sum(len(v.encode('utf-8')) for v in sources.values()) > 262144:
        raise ValueError('Source text budget exceeded')
    if type(observations) is not list or len(observations) > 64:
        raise ValueError('Bounded observations required')
    digests = {k: hashlib.sha256(v.encode('utf-8')).hexdigest() for k, v in sources.items()}
    matrix = {}
    for row in observations:
        if type(row) is not dict or set(row) != {'source_id', 'field', 'sha256', 'status', 'value', 'quote'}:
            raise ValueError('Invalid observation schema')
        source, field = row['source_id'], row['field']
        if type(source) is not str or type(field) is not str or source not in sources or field not in required_fields:
            raise ValueError('Observation outside declared scope')
        key = (source, field)
        if key in matrix:
            raise ValueError('Duplicate source-field observation')
        if type(row['sha256']) is not str or row['sha256'] != digests[source]:
            raise ValueError('Observation source version mismatch')
        status, value, quote = row['status'], row['value'], row['quote']
        if type(status) is not str or status not in ('value', 'absent', 'ambiguous'):
            raise ValueError('Unknown observation status')
        if status == 'absent':
            if value is not None or quote is not None:
                raise ValueError('Absent observation cannot assert a value or quote')
        else:
            if type(quote) is not str or not quote.strip() or quote not in sources[source]:
                raise ValueError('Exact nonempty source excerpt required')
            if status == 'value':
                if type(value) is not str or not value.strip() or len(value.encode('utf-8')) > 4096:
                    raise ValueError('Bounded canonical value required')
            elif value is not None:
                raise ValueError('Ambiguous observation cannot assert one value')
        matrix[key] = dict(row)
    fields = {}
    for field in required_fields:
        missing = sorted(s for s in sources if (s, field) not in matrix)
        rows = [matrix[s, field] for s in sorted(sources) if (s, field) in matrix]
        values = sorted({r['value'] for r in rows if r['status'] == 'value'})
        ambiguous = [r['source_id'] for r in rows if r['status'] == 'ambiguous']
        reasons = []
        if missing: reasons.append('unexamined_sources')
        if ambiguous: reasons.append('ambiguous_evidence')
        if len(values) > 1: reasons.append('conflicting_values')
        if not values: reasons.append('no_established_value')
        fields[field] = dict(ready=not reasons, value=values[0] if not reasons else None,
                             reasons=reasons, missing_sources=missing, observations=rows)
    ready = all(f['ready'] for f in fields.values())
    return dict(format='ocn.evidence-coverage.v1', ready=ready,
                values={k: v['value'] for k, v in fields.items()} if ready else {},
                fields=fields, source_versions=digests,
                scope='structural coverage and declared agreement; not semantic verification')
