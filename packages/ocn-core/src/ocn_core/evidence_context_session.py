"""Opt-in candidate-evidence selection and typed answer orchestration.

The cache stores paragraph IDs, never factual answers. Model judgments remain
unverified; exact references and source freshness do not certify meaning.
Callbacks are trusted integrations; budgets count invocations, not hidden APIs.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
from threading import Lock
from .document_adapter import DocumentAdapter
from .source_windows import split_passage


def _text(value, limit, label):
    if type(value) is not str or not value.strip() or len(value.encode()) > limit:
        raise ValueError('Bounded nonempty '+label+' required')


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


class EvidenceContextSession:
    def __init__(self, adapter, answerer, revision, *, selector=None,
                 max_callbacks=16, max_requests=32, cache_capacity=8,
                 max_source_bytes=65536, max_paragraphs=256, max_selected_paragraphs=4,
                 passage_mode="paragraph", normalize_unknown_references=False):
        if not isinstance(adapter, DocumentAdapter) or not callable(answerer) or not callable(revision):
            raise ValueError('Document adapter, answerer and policy revision callback required')
        if selector is not None and not callable(selector):raise ValueError('Callable selector required')
        if passage_mode not in ('paragraph','sentence'):
            raise ValueError('Passage mode must be paragraph or sentence')
        if type(normalize_unknown_references) is not bool:
            raise ValueError('Boolean unknown-reference normalization required')
        self._passage_mode=passage_mode;self._normalize_unknown=normalize_unknown_references
        for name, value, low, high in (
            ('callbacks',max_callbacks,1,128),('requests',max_requests,1,128),
            ('cache capacity',cache_capacity,0,32),('source bytes',max_source_bytes,1,262144),
            ('paragraphs',max_paragraphs,1,2048),('selected paragraphs',max_selected_paragraphs,1,2048)):
            if type(value) is not int or not low<=value<=high:raise ValueError('Invalid '+name+' limit')
        self._adapter=adapter;self._answerer=answerer;self._selector=selector;self._revision=revision
        self._max_callbacks=max_callbacks;self._max_requests=max_requests
        self._capacity=cache_capacity;self._max_bytes=max_source_bytes;self._max_paragraphs=max_paragraphs
        self._max_selected=max_selected_paragraphs
        self._calls=0;self._requests=0;self._cache=OrderedDict();self._lock=Lock()

    def _policy(self):
        revision=self._revision();_text(revision,1024,'policy revision');return revision

    def _invoke(self, callback, payload):
        if self._calls>=self._max_callbacks:raise RuntimeError('Callback budget exhausted')
        self._calls+=1
        result=callback(deepcopy(payload))
        if len(_encoded(result))>32768:raise ValueError('Callback result too large')
        return deepcopy(result)

    def _fresh(self, snapshots):
        current={i:self._adapter.read(i,discovery_bytes=len(d.text.encode())) for i,d in snapshots.items()}
        if any(current[i].sha256!=d.sha256 for i,d in snapshots.items()):
            raise ValueError('Source version changed during request')
        return current

    def answer(self, question, fields, document_ids):
        if not self._lock.acquire(blocking=False):raise RuntimeError('Evidence context session busy')
        try:
            if self._requests>=self._max_requests:raise RuntimeError('Request budget exhausted')
            self._requests+=1;before=self._calls
            _text(question,4096,'question')
            if type(fields) is not dict or not 1<=len(fields)<=8:raise ValueError('One to eight fields required')
            for k,v in fields.items():_text(k,128,'field name');_text(v,1024,'field description')
            fields=deepcopy(fields)
            if type(document_ids) is not tuple or not 1<=len(document_ids)<=8:raise ValueError('One to eight document IDs required')
            for i in document_ids:_text(i,128,'document ID')
            if len(set(document_ids))!=len(document_ids):raise ValueError('Distinct document IDs required')
            revision=self._policy()
            snapshots={i:self._adapter.read(i) for i in document_ids}
            if sum(len(d.text.encode()) for d in snapshots.values())>self._max_bytes:
                raise ValueError('Source context budget exceeded')
            paragraphs=[]
            # IDs encode source order/paragraph index, never source-provided names.
            for source_index,(ident,d) in enumerate(snapshots.items()):
                start=0
                for n,text in enumerate(d.text.split('\n\n')):
                    if text.strip():
                        paragraph=dict(id=f's{source_index}:p{n}',document_id=ident,
                                       start=start,end=start+len(text),text=text)
                        if self._passage_mode=='sentence':
                            for piece in split_passage(paragraph):
                                paragraphs.append(piece)
                                if len(paragraphs)>self._max_paragraphs:raise ValueError('Paragraph budget exceeded')
                        else:paragraphs.append(paragraph)
                    start+=len(text)+2
            if len(paragraphs)>self._max_paragraphs:raise ValueError('Paragraph budget exceeded')
            byid={p['id']:p for p in paragraphs}
            key=hashlib.sha256(_encoded(dict(question=question,fields=fields,
                sources=[(i,d.sha256) for i,d in snapshots.items()],revision=revision))).hexdigest()
            hit=self._selector is not None and key in self._cache
            needed=1+(self._selector is not None and not hit)
            if self._max_callbacks-self._calls<needed:
                raise RuntimeError('Insufficient callback budget for complete request')
            selection=None
            if self._selector is not None:
                selection=deepcopy(self._cache[key]) if hit else self._invoke(self._selector,dict(question=question,fields=fields,paragraphs=paragraphs))
                if type(selection) is not dict or set(selection)!=set(fields):raise ValueError('Exact selection field set required')
                for refs in selection.values():
                    if type(refs) is not list or len(refs)>self._max_selected or any(type(i) is not str or i not in byid for i in refs) or len(refs)!=len(set(refs)):
                        raise ValueError('Invalid paragraph selection')
                selected={i for refs in selection.values() for i in refs}
                supplied=[p for p in paragraphs if p['id'] in selected]
                if not hit:
                    self._fresh(snapshots)
                    if self._policy()!=revision:raise ValueError('Policy changed during selection')
            else:supplied=paragraphs
            value=self._invoke(self._answerer,dict(question=question,fields=fields,paragraphs=supplied))
            if type(value) is not dict or set(value)!=set(fields):raise ValueError('Exact answer field set required')
            allowed={p['id'] for p in supplied};answers={};withheld=[];withheld_refs={}
            for field,item in value.items():
                if type(item) is not dict or set(item)!={'status','answer','references'}:
                    raise ValueError('Explicit status, answer and references required')
                status,answer,refs=item['status'],item['answer'],item['references']
                if type(status) is not str or status not in ('supported','unknown','conflicting'):
                    raise ValueError('Invalid answer status')
                if type(refs) is not list or len(refs)>8 or any(type(i) is not str or i not in allowed for i in refs) or len(refs)!=len(set(refs)):
                    raise ValueError('Invalid answer references')
                if status=='supported':
                    _text(answer,2048,'proposed answer')
                    if not refs:raise ValueError('Proposed answer requires references')
                else:
                    explicit_null=answer is None
                    if type(answer) is str:
                        withheld.append(field);answer=None
                    elif answer is not None:raise ValueError('Invalid nonassertive answer')
                    if status=='unknown' and refs:
                        if self._normalize_unknown and explicit_null:
                            withheld_refs[field]=list(refs);refs=[]
                        else:raise ValueError('Unknown cannot assert evidence')
                    if status=='conflicting' and len(refs)<2:raise ValueError('Conflict requires two references')
                answers[field]=dict(status=status,answer=answer,references=list(refs))
            fresh=self._fresh(snapshots)
            if self._policy()!=revision:raise ValueError('Policy changed during answer')
            evictions=0
            if selection is not None and self._capacity:
                self._cache[key]=deepcopy(selection);self._cache.move_to_end(key)
                while len(self._cache)>self._capacity:self._cache.popitem(last=False);evictions+=1
            receipt=dict(fields=answers,evidence={p['id']:deepcopy(p) for p in supplied},
                sources={i:dict(sha256=d.sha256,path=fresh[i].path) for i,d in snapshots.items()},
                selection=deepcopy(selection),policy_revision=revision,semantic_verification=False,
                action_authorized=False,unknown_scope='provided_passages',withheld_text_fields=withheld,
                session=dict(requests=self._requests,callback_invocations=self._calls-before,
                    total_callback_invocations=self._calls,selection_cache_hit=hit,
                    selection_cache_entries=len(self._cache),selection_cache_evictions=evictions))
            if self._passage_mode!='paragraph':receipt['passage_mode']=self._passage_mode
            if self._normalize_unknown:receipt['withheld_unknown_references']=withheld_refs
            return receipt
        finally:self._lock.release()
