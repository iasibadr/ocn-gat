"""Opt-in semantic review gate around DocumentAgent.

Review is an attributed judgment by a trusted integration, not a proof of truth.
The reviewer receives the full pinned context, not just selected quotations.
Rejected/uncertain candidates are withheld and are not admitted to any memory.
The budget counts callback invocations, including failures, not hidden model calls.
"""
from copy import deepcopy
import hashlib,json
from threading import Lock
from .document_agent import DocumentAgent


def encoded(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()


class ReviewedDocumentAgent:
    def __init__(self,adapter,synthesizer,reviewer,*,reviewer_id,max_calls=16,max_context_bytes=16384):
        # Reuse runtime validation without performing I/O or inference.
        DocumentAgent(adapter,synthesizer,max_context_bytes=max_context_bytes)
        if not callable(reviewer):raise ValueError('Trusted reviewer required')
        if type(reviewer_id) is not str or not reviewer_id.strip() or len(reviewer_id.encode())>256:
            raise ValueError('Bounded explicit reviewer identifier required')
        if type(max_calls) is not int or not 2<=max_calls<=128:
            raise ValueError('Callback budget must be 2..128')
        self.adapter=adapter;self.synthesizer=synthesizer;self.reviewer=reviewer
        self.reviewer_id=reviewer_id;self.max_calls=max_calls;self.calls=0
        self.max_context_bytes=max_context_bytes;self.lock=Lock()

    def _reserve(self):
        if self.calls>=self.max_calls:raise RuntimeError('Review session callback budget exhausted')
        self.calls+=1

    def answer(self,question,document_ids):
        if not self.lock.acquire(blocking=False):raise RuntimeError('Review session busy')
        try:
            if self.max_calls-self.calls<2:raise RuntimeError('Two callback slots required before synthesis')
            context=[]
            def produce(q,documents):
                context.extend(deepcopy(documents))
                self._reserve()
                output=self.synthesizer(q,deepcopy(documents))
                if len(encoded(output))>32768:raise ValueError('Oversized synthesis envelope')
                return output
            candidate=DocumentAgent(self.adapter,produce,max_context_bytes=self.max_context_bytes).answer(question,document_ids)
            if candidate['abstain'] and candidate['answer'].strip():
                raise ValueError('Abstention must not carry an answer')
            payload={k:deepcopy(candidate[k]) for k in ('answer','abstain','citations')}
            candidate_sha256=hashlib.sha256(encoded(payload)).hexdigest()
            self._reserve()
            review=deepcopy(self.reviewer(question,deepcopy(context),deepcopy(payload)))
            if len(encoded(review))>16384:raise ValueError('Oversized review')
            if type(review) is not dict or set(review)!={'verdict','reason','evidence'}:
                raise ValueError('Explicit verdict, reason and evidence required')
            if review['verdict'] not in ('accepted','rejected','uncertain'):
                raise ValueError('Unknown semantic review verdict')
            if type(review['reason']) is not str or not review['reason'].strip() or len(review['reason'].encode())>2048:
                raise ValueError('Bounded nonempty review reason required')
            if type(review['evidence']) is not list or len(review['evidence'])>16:
                raise ValueError('Bounded review evidence required')
            if review['verdict']=='accepted' and not candidate['abstain'] and not review['evidence']:
                raise ValueError('Accepted answer requires review evidence')
            sources={d['document_id']:d for d in context}
            for reference in review['evidence']:
                if type(reference) is not dict or set(reference)!={'document_id','quote'}:
                    raise ValueError('Explicit review citation required')
                identity,quote=reference['document_id'],reference['quote']
                if (type(identity) is not str or identity not in sources or type(quote) is not str
                    or not quote.strip() or quote not in sources[identity]['text']):
                    raise ValueError('Review citation outside pinned context')
            # Even uncited context must still be current after the second callback.
            fresh={i:self.adapter.read(i,discovery_bytes=len(d['text'].encode())) for i,d in sources.items()}
            if any(fresh[i].sha256!=d['sha256'] for i,d in sources.items()):
                raise ValueError('Source changed during semantic review')
            accepted=review['verdict']=='accepted'
            result=deepcopy(candidate)
            if not accepted:result.update(answer='',abstain=True,citations=[])
            else:
                for citation in result['citations']:citation['path']=fresh[citation['document_id']].path
            result['document_bytes_read']+=sum(d.bytes_read for d in fresh.values())
            result['discovery_entries']+=sum(d.entries_scanned for d in fresh.values())
            result['semantic_review']=dict(review,reviewer_id=self.reviewer_id,
                candidate_sha256=candidate_sha256,scope='Attributed reviewer judgment, not formal truth proof')
            result['approved_for_use']=accepted and not candidate['abstain']
            result['callback_invocations_total']=self.calls
            return result
        finally:self.lock.release()
