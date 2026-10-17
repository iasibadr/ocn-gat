"""Opt-in repacking for a sink with atomic explicit nonacceptance."""
import hashlib
import json
from dataclasses import dataclass
from .scheduled import ScheduledAgent, ScheduledDNA

@dataclass(frozen=True)
class RepackingDNA(ScheduledDNA):
    refusal_contract: str = 'atomic_nonacceptance_v1'

    def __post_init__(self):
        super().__post_init__()
        if self.refusal_contract != 'atomic_nonacceptance_v1':
            raise ValueError('Unknown refusal contract')


@dataclass(frozen=True)
class ReservedRepackingDNA(RepackingDNA):
    destination_capacity: int = 16
    destination_reserve: int = 1

    def __post_init__(self):
        super().__post_init__()
        if (type(self.destination_capacity) is not int or self.destination_capacity<1
                or type(self.destination_reserve) is not int
                or not 0<=self.destination_reserve<self.destination_capacity):
            raise ValueError('Invalid destination admission contract')

    def destination_descriptor(self):
        return dict(format='ocn.local-reserved.v1',capacity=self.destination_capacity,
                    reserve=self.destination_reserve,scope='single_stream_local_admission')


class RepackingAgent(ScheduledAgent):
    def __init__(self, policy, initial_paths, dna, seed=0):
        if not isinstance(dna, RepackingDNA):
            raise ValueError('Repacking DNA required')
        super().__init__(policy, initial_paths, dna, seed)

    def check_refusal_contract(self, tools):
        if getattr(tools, 'supports_atomic_refusal', False) is not True:
            raise ValueError('Habitat must guarantee atomic nonacceptance on refusal')
        if isinstance(self.dna,ReservedRepackingDNA):
            descriptor=getattr(tools,'admission_descriptor',None)
            if (type(descriptor) is not dict
                    or type(descriptor.get('capacity')) is not int
                    or type(descriptor.get('reserve')) is not int
                    or descriptor!=self.dna.destination_descriptor()):
                raise ValueError('Destination admission contract mismatch')

    def before_request(self, n, tools):
        self.check_refusal_contract(tools)
        super().before_request(n, tools)

    def emit_pending(self, n, tools):
        self.check_refusal_contract(tools)
        super().emit_pending(n, tools)
        pending = self.retirement['pending']
        if not pending or not any(r.get('accepted') is False and
                                  r.get('sequence') == pending[0]['sequence']
                                  for r in self.last_emissions):
            return
        # Only the head has crossed the membrane; no exposed tail may be changed.
        if any(e['sealed'] for e in pending[1:]):
            raise ValueError('Cannot repack an exposed tail')
        sequence = pending[0]['sequence']
        if len(pending) > 1:
            self.retirement['merges'] += len(pending) - 1
            representation = [(e['sequence'], e['digest'], e['count']) for e in pending]
            digest = hashlib.sha256(json.dumps(representation,separators=(',',':')).encode()).hexdigest()
            count = sum(e['count'] for e in pending)
            pending[:] = [dict(sequence=sequence, digest=digest, count=count, sealed=False)]
        else:
            pending[0]['sealed'] = False
        self.retirement['sequence'] = sequence
        born = self.emission_state['born']
        self.emission_state['born'] = {str(sequence): min(born.values())}
