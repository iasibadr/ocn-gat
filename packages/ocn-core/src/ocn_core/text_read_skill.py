"""Learn one exact short-string read path from independently verified examples.

No generated code, fuzzy matching, normalization, inference of prose semantics,
or automatic task selection. One session must retain the same field objective.
Shares the bounded JSON grammar of mass_read_skill; strings are at most 160 chars.
"""
from dataclasses import dataclass
import hashlib
from .mass_read_skill import encoded, shape, read_at, _validate_examples


@dataclass(frozen=True)
class TextContract:
    connector: str
    revision: str
    identity: tuple
    value: tuple
    shape_sha256: str
    acceptance_sha256: str

    def apply(self,record,*,connector,revision,expected_identity):
        raw=encoded(record)
        if (connector,revision)!=(self.connector,self.revision):
            raise ValueError('Contract outside pinned connector revision')
        if hashlib.sha256(encoded(shape(record))).hexdigest()!=self.shape_sha256:
            raise ValueError('Observed schema changed')
        identity=read_at(record,self.identity)
        if type(identity) is not str or identity!=expected_identity:raise ValueError('Wrong entity')
        value=read_at(record,self.value)
        if type(value) is not str or not 1<=len(value)<=160:
            raise ValueError('Exact short text required')
        return dict(identity=identity,value=value,source_sha256=hashlib.sha256(raw).hexdigest(),
                    contract_revision=self.revision,paths=dict(identity=self.identity,value=self.value))


def discover(examples,*,connector,revision):
    if any(type(v) is not str or not v.strip() or len(v)>128 for v in (connector,revision)):
        raise ValueError('Explicit connector and revision required')
    _validate_examples(examples)
    paths=[]
    def walk(value,prefix=()):
        if type(value) is dict:
            for key,child in sorted(value.items()):walk(child,prefix+(key,))
        else:paths.append(prefix)
    walk(examples[0]['record'])
    if len(paths)>32:raise ValueError('Leaf budget exceeded')
    def matches(path,key):
        try:return all(type(read_at(e['record'],path)) is str and read_at(e['record'],path)==e[key] for e in examples)
        except ValueError:return False
    identities=[p for p in paths if matches(p,'identity')]
    values=[p for p in paths if p not in identities and matches(p,'expected')]
    if len(identities)!=1 or len(values)!=1:
        raise ValueError('Expected one unambiguous identity and text path')
    contract=TextContract(connector,revision,identities[0],values[0],
        hashlib.sha256(encoded(shape(examples[0]['record']))).hexdigest(),
        hashlib.sha256(encoded(examples)).hexdigest())
    for e in examples:
        if contract.apply(e['record'],connector=connector,revision=revision,expected_identity=e['identity'])['value']!=e['expected']:
            raise ValueError('Candidate failed host acceptance')
    return contract,dict(candidates=len(paths),accepted=1,model_calls=0,kind='exact_text')
