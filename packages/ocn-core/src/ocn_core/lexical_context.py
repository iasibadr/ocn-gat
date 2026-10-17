"""Optional bounded lexical paragraph selection for EvidenceContextSession.

Ranks candidates, never certifies completeness or truth. Entity coverage prefers
separate sources containing alphanumeric identifiers explicitly in the question.
No model calls, filesystem access, hidden memory or learned synonym dictionary.
"""
from dataclasses import dataclass
from .evidence_context_session import _text

from collections import Counter
import math,re,unicodedata

STOP=set('le la les de du des un une et en a au aux pour est sont quel quelle quelles quels qui que avec dans ce cette il son sa ses doit'.split())
def tokens(text):
    text=''.join(c for c in unicodedata.normalize('NFD',text.lower()) if not unicodedata.combining(c))
    return [w for w in re.findall(r'\w+',text) if w not in STOP]

def rank(request,limit):
    paragraphs=request['paragraphs'];counts=[Counter(tokens(p['text'])) for p in paragraphs]
    lengths=[sum(c.values()) for c in counts];average=sum(lengths)/max(1,len(lengths)) or 1
    df=Counter(t for c in counts for t in c)
    result={}
    for field,description in request['fields'].items():
        query=set(tokens(request['question']+' '+description))
        def score(i):
            c=counts[i]
            return sum(math.log(1+(len(counts)-df[t]+.5)/(df[t]+.5))*c[t]*2.2/
                (c[t]+1.2*(.25+.75*lengths[i]/average)) for t in query if c[t])
        ranked=sorted(((score(i),i) for i in range(len(paragraphs))),key=lambda p:(-p[0],p[1]))
        result[field]=[paragraphs[i]['id'] for value,i in ranked[:limit] if value>0]
    return result

def bm25(request):return rank(request,4)

def entity_coverage(request):
    """Prefer distinct sources mentioning explicit alphanumeric query identifiers."""
    anchors={t for t in tokens(request['question']) if any(c.isdigit() for c in t) and any(c.isalpha() for c in t)}
    if not anchors:return bm25(request)
    catalog={p['id']:p for p in request['paragraphs']}
    ranked=rank(request,len(catalog));result={}
    for field,ids in ranked.items():
        matching=[i for i in ids if anchors.intersection(tokens(catalog[i]['text']))]
        chosen=[];sources=set()
        for i in matching:
            source=catalog[i]['document_id']
            if source not in sources:
                chosen.append(i);sources.add(source)
                if len(chosen)==4:break
        for i in ids:
            if len(chosen)==4:break
            if i not in chosen:chosen.append(i)
        result[field]=chosen
    return result


@dataclass(frozen=True)
class LexicalContextSelector:
    entity_coverage: bool = False
    deduplicate: bool = False

    def __post_init__(self):
        if type(self.entity_coverage) is not bool:
            raise ValueError('Boolean entity coverage required')
        if type(self.deduplicate) is not bool:
            raise ValueError('Boolean deduplication required')

    def revision(self):
        return ('ocn.lexical-context.v1:coverage='+str(int(self.entity_coverage))
                +(':exact-dedup-v1' if self.deduplicate else ''))

    def __call__(self, request):
        if type(request) is not dict or set(request)!={'question','fields','paragraphs'}:
            raise ValueError('Explicit question, fields and paragraphs required')
        _text(request['question'],4096,'question')
        fields=request['fields'];paragraphs=request['paragraphs']
        if type(fields) is not dict or not 1<=len(fields)<=8:
            raise ValueError('One to eight fields required')
        for name,description in fields.items():
            _text(name,128,'field');_text(description,1024,'field description')
        if type(paragraphs) is not list or len(paragraphs)>2048:
            raise ValueError('Bounded paragraph catalog required')
        ids=set();size=0
        for p in paragraphs:
            if type(p) is not dict or set(p)!={'id','document_id','start','end','text'}:
                raise ValueError('Explicit paragraph span required')
            _text(p['id'],128,'paragraph ID');_text(p['document_id'],128,'document ID')
            if p['id'] in ids:raise ValueError('Distinct paragraph IDs required')
            ids.add(p['id'])
            if (type(p['text']) is not str or type(p['start']) is not int
                or type(p['end']) is not int or p['start']<0
                or p['end']-p['start']!=len(p['text'])):
                raise ValueError('Invalid paragraph span')
            size+=len(p['text'].encode())
            if size>262144:raise ValueError('Source text budget exceeded')
        if self.deduplicate:
            seen=set();unique=[]
            for paragraph in paragraphs:
                # Exact text only: no semantic equivalence, whitespace folding,
                # negation removal or filesystem deletion is implied.
                if paragraph['text'] not in seen:
                    seen.add(paragraph['text']);unique.append(paragraph)
            request=dict(request,paragraphs=unique)
        return entity_coverage(request) if self.entity_coverage else bm25(request)
