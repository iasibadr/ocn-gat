"""Bounded host-calibrated mass reading skill (grams/kilograms). No eval, generated code or networking.

Acceptance examples and unit tables come from the host. Passing finite examples
does not prove semantic correctness on every future record.
"""
from dataclasses import dataclass
import hashlib
import json

from .quantity_normalization import canonical_quantity


def encoded(value):
    try:
        raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    except (TypeError, RecursionError, OverflowError) as exc:
        raise ValueError('Bounded JSON input required') from exc
    if len(raw)>16384:raise ValueError('Contract input exceeds byte budget')
    return raw


def shape(value,depth=0,_nodes=None):
    if _nodes is None:_nodes=[0]
    _nodes[0]+=1
    if _nodes[0]>256:raise ValueError('Structure node budget exceeded')
    if depth>6:raise ValueError('Structure too deep')
    if type(value) is dict:
        if len(value)>32 or any(type(k) is not str or not 1<=len(k)<=128 for k in value):
            raise ValueError('Bounded string keys required')
        return {k:shape(v,depth+1,_nodes) for k,v in sorted(value.items())}
    if type(value) is str:
        if len(value)>16384:raise ValueError('String budget exceeded')
        return 'string'
    if type(value) is int:
        if value.bit_length()>256:raise ValueError('Integer budget exceeded')
        return 'integer'
    raise ValueError('Only nested objects, strings and integers supported')


def path(value):
    if (type(value) is not list or not 1<=len(value)<=6
            or any(type(k) is not str or not 1<=len(k)<=128 for k in value)):
        raise ValueError('Bounded explicit key path required')
    return tuple(value)


def read_at(record,keys):
    value=record
    for key in keys:
        if type(value) is not dict or key not in value:raise ValueError('Contract path absent')
        value=value[key]
    return value


@dataclass(frozen=True)
class Contract:
    connector: str
    revision: str
    identity: tuple
    quantity: tuple
    unit: tuple | None
    shape_sha256: str
    acceptance_sha256: str

    def apply(self,record,*,connector,revision,expected_identity):
        observed_shape=shape(record)
        raw=encoded(record)
        if connector!=self.connector or revision!=self.revision:raise ValueError('Contract outside pinned connector revision')
        if hashlib.sha256(encoded(observed_shape)).hexdigest()!=self.shape_sha256:
            raise ValueError('Observed schema changed')
        identity=read_at(record,self.identity)
        if type(identity) is not str or identity!=expected_identity:raise ValueError('Wrong entity')
        amount=read_at(record,self.quantity)
        if self.unit is None:
            if type(amount) is not str:raise ValueError('Raw quantity string required')
            raw_amount=amount
        else:
            unit=read_at(record,self.unit)
            if type(amount) not in (str,int) or type(unit) is not str:raise ValueError('Scalar and unit required')
            raw_amount=str(amount)+' '+unit
        normalized=canonical_quantity(raw_amount,base_unit='g',factors={'g':'1','kg':'1000'})
        return dict(identity=identity,**normalized,source_sha256=hashlib.sha256(raw).hexdigest(),
                    contract_revision=self.revision,paths=dict(identity=self.identity,quantity=self.quantity,unit=self.unit))


def accept(proposal,examples,*,connector,revision):
    if (type(connector) is not str or not connector.strip() or len(connector)>128
            or type(revision) is not str or not revision.strip() or len(revision)>128):
        raise ValueError('Explicit connector and revision required')
    if type(proposal) is not dict or set(proposal)!={'identity','quantity','unit'}:
        raise ValueError('Read paths only; no executable extensions')
    _validate_examples(examples)
    contract=Contract(connector,revision,path(proposal['identity']),path(proposal['quantity']),
        None if proposal['unit'] is None else path(proposal['unit']),
        hashlib.sha256(encoded(shape(examples[0]['record']))).hexdigest(),
        hashlib.sha256(encoded(examples)).hexdigest())
    for e in examples:
        value=contract.apply(e['record'],connector=connector,revision=revision,expected_identity=e['identity'])
        if value['value']!=e['expected']:raise ValueError('Candidate failed host acceptance')
    return contract


def _validate_examples(examples):
    if type(examples) is not list or not 2<=len(examples)<=8:
        raise ValueError('Two to eight host acceptance examples required')
    for e in examples:
        if type(e) is not dict or set(e)!={'record','identity','expected'}:
            raise ValueError('Explicit host expected result required')
        if (type(e['identity']) is not str or not 1<=len(e['identity'])<=128
                or type(e['expected']) is not str or not 1<=len(e['expected'])<=160
                or type(e['record']) is not dict):
            raise ValueError('Bounded host identity, quantity and record required')
        shape(e['record'])
    encoded(examples)
    if len({e['identity'] for e in examples})<2 or len({e['expected'] for e in examples})<2:
        raise ValueError('Distinct entities and expected values required')


def discover(examples, *, connector, revision, max_candidates=128):
    if type(max_candidates) is not int or not 1<=max_candidates<=128:
        raise ValueError('Candidate budget must be 1..128')
    _validate_examples(examples)
    leaves=[]
    def walk(value,prefix=()):
        if type(value) is dict:
            for k,v in sorted(value.items()):walk(v,prefix+(k,))
        else:leaves.append(prefix)
    shape(examples[0]['record'])
    walk(examples[0]['record'])
    if len(leaves)>32:raise ValueError('Leaf budget exceeded')
    def matches_identity(p):
        try:return all(read_at(e['record'],p)==e['identity'] for e in examples)
        except (KeyError,ValueError):return False
    identities=[p for p in leaves if matches_identity(p)]
    quantities=[p for p in leaves if p not in identities]
    units=[None]+[p for p in quantities if type(read_at(examples[0]['record'],p)) is str]
    count=len(identities)*len(quantities)*len(units)
    if count>max_candidates:raise ValueError('Candidate budget exceeded')
    accepted=[]
    for i in identities:
        for q in quantities:
            for u in units:
                proposal=dict(identity=list(i),quantity=list(q),unit=None if u is None else list(u))
                try:contract=accept(proposal,examples,connector=connector,revision=revision)
                except (ValueError,KeyError,TypeError):continue
                accepted.append(contract)
    if len(accepted)!=1:
        raise ValueError('Expected one validated contract; found '+str(len(accepted)))
    return accepted[0],dict(candidates=count,accepted=1,model_calls=0)


class MassSkillSession:
    """Single-owner in-memory skill reuse; caller owns transport and lifecycle.

Host calibration is copied at construction and cannot be extended by a response.
This session authorizes no I/O. A new response is required on every call. close()
clears its method and prevents further reading. No result cache is maintained.
"""
    def __init__(self, *, connector, calibration):
        if type(connector) is not str or not connector.strip() or len(connector)>128:
            raise ValueError('Explicit connector required')
        if type(calibration) is not dict or not 1<=len(calibration)<=8:
            raise ValueError('One to eight host revisions required')
        for revision, examples in calibration.items():
            if type(revision) is not str or not revision.strip() or len(revision)>128:
                raise ValueError('Explicit revision required')
            _validate_examples(examples)
        self._calibration=json.loads(json.dumps(calibration))
        self.connector=connector
        self._contract=None
        self._closed=False
        self.acquisitions=0

    def read(self, record, *, revision, expected_identity):
        if self._closed:raise ValueError('Skill session is closed')
        if type(revision) is not str or revision not in self._calibration:
            raise ValueError('Revision not authorized by host')
        if type(expected_identity) is not str or not 1<=len(expected_identity)<=128:
            raise ValueError('Explicit bounded entity required')
        if self._contract is None or self._contract.revision!=revision:
            self._contract=None
            self.acquisitions+=1
            self._contract,_=discover(self._calibration[revision],connector=self.connector,revision=revision)
        return self._contract.apply(record,connector=self.connector,revision=revision,
                                    expected_identity=expected_identity)

    def close(self):
        self._contract=None
        self._calibration.clear()
        self._closed=True
