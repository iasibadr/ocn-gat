"""Exact source windows: simple sentence boundaries, not linguistic truth.

No characters are paraphrased or normalized. Lexical retrieval can still miss
relevant material; the neighboring sentence is a bounded context heuristic.
"""
import re


def split_passage(paragraph):
    text=paragraph['text']
    bounds=[0]+[m.start() for m in re.finditer(r'(?<=[.!?])(?=\s+[A-ZÀ-ÖØ-Þ])',text)]+[len(text)]
    for index,(start,end) in enumerate(zip(bounds,bounds[1:])):
        if start!=end:
            yield dict(id=paragraph['id']+f':c{index}',document_id=paragraph['document_id'],
                start=paragraph['start']+start,end=paragraph['start']+end,text=text[start:end])


def select_windows(payload):
    # Lazy import avoids a cycle with the session's input validation helpers.
    from .lexical_context import LexicalContextSelector,rank
    LexicalContextSelector()(payload)
    paragraphs=payload['paragraphs'];groups={}
    for p in paragraphs:
        match=re.fullmatch(r'(s\d+:p\d+):c(\d+)',p['id'])
        if not match:raise ValueError('Session-generated sentence IDs required')
        groups.setdefault((p['document_id'],match.group(1)),[]).append(p['id'])
    ranked=rank(payload,len(paragraphs))
    matches={ident for values in ranked.values() for ident in values};selected=set(matches)
    for group in groups.values():
        for index,ident in enumerate(group):
            if ident in matches:selected.update(group[max(0,index-1):index+2])
    ids=[p['id'] for p in paragraphs if p['id'] in selected]
    trace=dict(matched_ids=sorted(matches),selected_ids=ids,
        excluded_ids=[p['id'] for p in paragraphs if p['id'] not in selected],
        semantic_verification=False,derived_summary=False,one_neighbor_each_side=True,
        fits=False)
    return {field:list(ids) for field in payload['fields']},trace
