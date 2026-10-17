"""Host-authorized bounded skill acquisition for shared classical/OCN workers."""
from collections import OrderedDict
import hashlib,json
from ocn_core.mass_read_skill import discover,encoded,_validate_examples


class SkillBank:
    def __init__(self,capacity=2,*,kind='mass'):
        if type(capacity) is not int or not 1<=capacity<=8:raise ValueError('Bounded capacity required')
        if kind not in ('mass','text'):raise ValueError('Unknown structural skill kind')
        from .text_read_skill import discover as discover_text
        self.discover=discover if kind=='mass' else discover_text
        self.capacity=capacity;self.authority={};self.entries=OrderedDict();self.audit=[]
        self.attempts=0;self.hits=0;self.negative_hits=0;self.evictions=0

    def authorize(self,connector,revision,examples):
        # Only a host caller can invoke this method; source data never calls it.
        if any(type(v) is not str or not v.strip() or len(v)>128 for v in (connector,revision)):
            raise ValueError('Explicit host connector/revision required')
        _validate_examples(examples)
        if connector not in self.authority and len(self.authority)>=8:raise ValueError('Host connector bound exceeded')
        digest=hashlib.sha256(encoded(examples)).hexdigest()
        previous=self.authority.get(connector)
        if previous and (previous['revision'],previous['digest'])!=(revision,digest):
            self.entries.pop(connector,None)
            self.audit.append(dict(event='revoked',connector=connector,revision=previous['revision']))
        self.authority[connector]=dict(revision=revision,digest=digest,examples=json.loads(json.dumps(examples)))
        self.audit=self.audit[-16:]

    def authorized(self,connector,revision):
        authority=self.authority.get(connector)
        if authority is None or authority['revision']!=revision:raise ValueError('Revision outside host authority')
        return authority

    def read(self,connector,revision,record,identity,*,acquire=True):
        authority=self.authorized(connector,revision)
        if connector in self.entries:
            contract,receipt=self.entries[connector]
            if contract is None:self.negative_hits+=1
            else:
                self.entries.move_to_end(connector)
                self.hits+=1
        else:
            if not acquire:return dict(status="not_acquired")
            self.attempts+=1
            try:contract,receipt=self.discover(authority['examples'],connector=connector,revision=revision)
            except ValueError as exc:contract=None;receipt=dict(rejected=str(exc))
            self.entries[connector]=(contract,receipt)
            if len(self.entries)>self.capacity:
                dropped,_=self.entries.popitem(last=False);self.evictions+=1
                self.audit.append(dict(event='evicted',connector=dropped));self.audit=self.audit[-16:]
        if contract is None:return dict(status='unsupported',receipt=receipt)
        # A bad current response must fail, not fall through into weaker authority.
        return dict(status='value',output=contract.apply(record,connector=connector,revision=revision,expected_identity=identity))

    def stats(self):
        return dict(attempts=self.attempts,hits=self.hits,negative_hits=self.negative_hits,
                    evictions=self.evictions,retained=list(self.entries),audit=list(self.audit))
