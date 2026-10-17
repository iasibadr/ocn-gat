"""Immutable, host-selected integer task contracts. No arbitrary expressions."""
from dataclasses import dataclass

@dataclass(frozen=True)
class TaskSpec:
    operation: str
    sources: tuple

    def __post_init__(self):
        if self.operation not in ('sum','minimum','maximum','difference'):
            raise ValueError('Unsupported task operation')
        if (type(self.sources) is not tuple or not self.sources
                or any(type(s) is not str or not s for s in self.sources)
                or len(set(self.sources))!=len(self.sources)):
            raise ValueError('Task sources must be distinct nonempty identifiers')
        if self.operation=='difference' and len(self.sources)!=2:
            raise ValueError('Difference requires exactly two ordered sources')

    def evaluate(self,values):
        if (type(values) is not dict or set(values)!=set(self.sources)
                or any(type(v) is not int for v in values.values())):
            raise ValueError('Task requires exactly its verified integer inputs')
        ordered=[values[s] for s in self.sources]
        if self.operation=='sum':return sum(ordered)
        if self.operation=='minimum':return min(ordered)
        if self.operation=='maximum':return max(ordered)
        return ordered[0]-ordered[1]
