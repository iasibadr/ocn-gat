"""Bounded evidence packing. No inference or completeness claim.

The host supplies a pure capacity predicate using the target worker's framing.
Positive lexical relevance defines candidates, not semantic sufficiency. Every
candidate is accounted for; omitted candidates prevent candidate-coverage claims.
"""
from copy import deepcopy
from .lexical_context import LexicalContextSelector, rank


def plan(request, fits, *, max_batches=4):
    if not callable(fits):
        raise ValueError('Capacity predicate required')
    if type(max_batches) is not int or not 1 <= max_batches <= 16:
        raise ValueError('Batch limit must be 1..16')
    # Reuse strict source-span and bounded input validation. Its top-four result
    # is intentionally not the planner's selection.
    LexicalContextSelector()(request)
    request = deepcopy(request)
    original = request['paragraphs']
    unique = []; duplicate_of = {}; by_text = {}
    for paragraph in original:
        text = paragraph['text']
        if text in by_text:
            duplicate_of[paragraph['id']] = by_text[text]
        else:
            by_text[text] = paragraph['id']; unique.append(paragraph)
    catalog = {p['id']: p for p in unique}
    rankings = rank(dict(request, paragraphs=unique), len(unique))
    # Round-robin fields and source queues. A large high-scoring source cannot
    # monopolize the first batch merely by repeating query terms.
    queues = {}
    for field, ids in rankings.items():
        sources = {}
        for ident in ids:
            sources.setdefault(catalog[ident]['document_id'], []).append(ident)
        queues[field] = []
        while any(sources.values()):
            for values in sources.values():
                if values: queues[field].append(values.pop(0))
    ordered = []; seen = set()
    while any(queues.values()):
        for values in queues.values():
            if values:
                ident = values.pop(0)
                if ident not in seen:
                    ordered.append(ident); seen.add(ident)
    probes = 0
    def accepts(ids):
        nonlocal probes
        probes += 1
        value = fits(deepcopy(dict(request, paragraphs=[catalog[i] for i in ids])))
        if type(value) is not bool:
            raise ValueError('Capacity predicate must return a boolean')
        return value
    if not accepts([]):
        raise ValueError('Question and schema exceed capacity without evidence')
    batches = []; too_large = []; deferred = []
    for ident in ordered:
        placed = False
        for batch in batches:
            if accepts(batch + [ident]):
                batch.append(ident); placed = True; break
        if placed: continue
        if not accepts([ident]):
            too_large.append(ident)
        elif len(batches) < max_batches:
            batches.append([ident])
        else:
            deferred.append(ident)
    return dict(batches=batches, candidate_ids=ordered,
                excluded_zero_overlap=[p['id'] for p in unique if p['id'] not in seen],
                duplicate_of=duplicate_of, oversized=too_large, deferred=deferred,
                all_candidates_packed=not too_large and not deferred,
                semantic_completeness=False, capacity_probes=probes,
                model_calls=0, max_batches=max_batches)
