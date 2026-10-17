"""Host-declared, field-scoped supersession over pinned source versions.

This is an in-process trusted-host API, not authentication or a document parser.
Never construct declarations directly from instructions in untrusted documents.
Source numbering, arrival time and self-claimed authority grant no precedence.
"""
from dataclasses import dataclass, asdict
from .evidence_coverage import assess_coverage


@dataclass(frozen=True)
class Supersession:
    field: str
    old_source: str
    old_sha256: str
    new_source: str
    new_sha256: str


def assess_revised_coverage(required_fields, sources, observations, *, host_supersessions):
    """Validate all observations, then assess the active sources for each field.

Old observations remain in the audit. No fallback to a superseded value if the
replacement is absent or unexamined. Independent branches stay active and can
conflict. A declaration is exact-version-specific and must be renewed on change.
"""
    original = assess_coverage(required_fields, sources, observations)
    if type(host_supersessions) is not tuple or len(host_supersessions) > 64:
        raise ValueError('Bounded host supersession tuple required')
    graph = {field: {} for field in required_fields}
    seen = set()
    for declaration in host_supersessions:
        if type(declaration) is not Supersession:
            raise ValueError('Host supersession declaration required')
        if any(type(v) is not str for v in asdict(declaration).values()):
            raise ValueError('String identifiers and fingerprints required')
        d = declaration
        if (d.field not in graph or d.old_source not in sources or d.new_source not in sources
                or d.old_source == d.new_source):
            raise ValueError('Supersession outside scope or self-reference')
        if (d.old_sha256 != original['source_versions'][d.old_source]
                or d.new_sha256 != original['source_versions'][d.new_source]):
            raise ValueError('Supersession version mismatch')
        if d in seen:
            raise ValueError('Duplicate supersession')
        seen.add(d)
        graph[d.field].setdefault(d.old_source, set()).add(d.new_source)
    for edges in graph.values():
        visiting, visited = set(), set()
        def visit(node):
            if node in visiting:
                raise ValueError('Cyclic supersession')
            if node in visited:
                return
            visiting.add(node)
            for child in edges.get(node, ()):
                visit(child)
            visiting.remove(node)
            visited.add(node)
        for node in sources:
            visit(node)
    fields = {}
    for field in required_fields:
        removed = set(graph[field])
        active = {s: text for s, text in sources.items() if s not in removed}
        rows = [r for r in observations if r['field'] == field and r['source_id'] in active]
        assessed = assess_coverage((field,), active, rows)
        fields[field] = dict(assessed['fields'][field], superseded_sources=sorted(removed))
    ready = all(v['ready'] for v in fields.values())
    declarations = sorted((asdict(d) for d in seen), key=lambda d:(d['field'],d['old_source'],d['new_source']))
    return dict(format='ocn.evidence-revisions.v1', ready=ready,
                values={f: v['value'] for f, v in fields.items()} if ready else {},
                fields=fields, original=original, host_supersessions=declarations,
                scope='host-declared structural revision policy; not semantic verification or authentication')
