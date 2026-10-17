"""Explicit persistent probe allowance, using the existing attempt-budget writer.

Trusted local host. This persists an attempt count, not cycle state or effects.
The inherited filename model-budget.json is an implementation detail in a distinct
probe directory; this allowance must never share a GAT model-budget directory.
"""
import json,os,stat
from pathlib import Path
from .application import locked
from .experience_memory import ExperienceMemory,label
from . import model_budget


def unique(pairs):
    value=dict(pairs)
    if len(value)!=len(pairs):raise ValueError('Duplicate authority fields')
    return value


class PersistentProbeBudget:
    @classmethod
    def create(cls,root,*,limit,memory,coordinate_contract):
        expected=cls.binding(limit,memory,coordinate_contract)
        root=Path(root).absolute()
        if root.is_symlink():raise ValueError('Probe directory symlink forbidden')
        root.mkdir(mode=0o700)  # Exclusive: never reinitialize an existing budget.
        with (root/'probe-authority.json').open('x') as f:
            json.dump(expected,f,sort_keys=True);f.flush();os.fsync(f.fileno())
        model_budget.initialize(root,limit)
        return cls(root,limit=limit,memory=memory,coordinate_contract=coordinate_contract)

    @staticmethod
    def binding(limit,memory,coordinate_contract):
        if type(limit) is not int or not 1<=limit<=64:raise ValueError('Probe limit must be 1..64')
        if type(memory) is not ExperienceMemory:raise ValueError('ExperienceMemory required')
        label(coordinate_contract)
        return dict(format='ocn.probe-authority.v1',limit=limit,memory_path=str(memory.path.resolve()),experience_contract=memory.contract_id,coordinate_contract=coordinate_contract)

    def __init__(self,root,*,limit,memory,coordinate_contract):
        self.expected=self.binding(limit,memory,coordinate_contract)
        self.root=Path(root).absolute()
        if self.root.is_symlink() or not self.root.is_dir():raise ValueError('Existing probe directory required')
        self.remaining()

    def check_binding(self,memory,coordinate_contract):
        if self.binding(self.expected['limit'],memory,coordinate_contract)!=self.expected:
            raise ValueError('Probe authority mismatch')

    def _read_locked(self):
        fd=os.open(self.root/'probe-authority.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('Regular authority required')
            raw=f.read(8193)
        if len(raw)>8192:raise ValueError('Probe authority too large')
        actual=json.loads(raw,object_pairs_hook=unique)
        if (type(actual) is not dict or set(actual)!=set(self.expected)
            or any(type(actual[k]) is not type(v) for k,v in self.expected.items())
            or actual!=self.expected):
            raise ValueError('Probe authority changed or corrupted')
        return model_budget.read(self.root,self.expected['limit'])

    def remaining(self):
        with locked(self.root):
            state=self._read_locked();return state['limit']-state['used']

    def reserve(self):
        with locked(self.root):
            self._read_locked()
            state=model_budget.reserve(self.root,self.expected['limit'])
            return dict(limit=state['limit'],used=state['used'],remaining=state['limit']-state['used'])
