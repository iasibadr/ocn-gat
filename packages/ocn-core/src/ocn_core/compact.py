"""Lossy retirement summaries: bounded metadata, immutable attempted batches."""
from dataclasses import dataclass, asdict
import hashlib
import json
from .controller import Agent, Fault, Predictor
from .dissipation import DissipativeDNA,DissipativeAgent
from .reservoir import RetirementReservoir

@dataclass(frozen=True)
class CompactDNA(DissipativeDNA):
    emission_phase: str = "before"
    aggregation: str = "overflow"
    known_unsupported_reactive: bool = False
    learning_scope: str = "shared"
    temperature_scope: str = "shared"
    def __post_init__(self):
        super().__post_init__()
        if self.emission_phase not in ("before","after"):raise ValueError("Invalid emission phase")
        if self.aggregation not in ("overflow","eager"):raise ValueError("Invalid aggregation")
        if type(self.known_unsupported_reactive) is not bool:raise ValueError("Invalid diagnostic gate")
        if self.learning_scope not in ("shared","source") or self.temperature_scope not in ("shared","source"):raise ValueError("Invalid cell scope")
        if self.retirement_capacity<2:
            raise ValueError('Compaction requires a frozen slot and an open slot')

class CompactAgent(DissipativeAgent):
    def __init__(self,policy,initial_paths,dna,seed=0):
        if not isinstance(dna,CompactDNA):raise ValueError('Compact DNA required')
        super().__init__(policy,initial_paths,dna,seed)
        self.retirement.update(retired_events=0,accepted_events=0,merges=0)
        self._pending_maintenance=None
        self.cell_models={s:(self.model if i==0 else Predictor(policy)) for i,s in enumerate(dna.source_ids)} if dna.learning_scope=='source' else {}
        self.cell_temperatures={s:.04 for s in dna.source_ids} if dna.temperature_scope=='source' else {}

    def predictor_for(self,source):
        return self.cell_models[source] if self.cell_models else self.model

    def temperature_for(self,source):
        return self.cell_temperatures[source] if self.cell_temperatures else self.temperature

    def record_temperature(self,source,value):
        if self.cell_temperatures:
            self.cell_temperatures[source]=value
            self.temperature=sum(self.cell_temperatures.values())/len(self.cell_temperatures)
        else:super().record_temperature(source,value)

    def action_mask(self,source,allowed):
        allowed=super().action_mask(source,allowed)
        if self.dna.known_unsupported_reactive and self.descriptors[source].get('codec') not in self.dna.allowed_codecs:
            allowed=allowed.copy();allowed[1:]=False
        return allowed

    def replace_memory(self,field,source,value,n):
        old=getattr(self,field)[source]
        if old==value:return
        state=self.retirement;pending=state['pending']
        digest=hashlib.sha256(json.dumps(dict(field=field,source=source,old=old,new=value),sort_keys=True).encode()).hexdigest()
        if (pending and not pending[-1]["sealed"] and self.dna.aggregation=="eager") or len(pending)>=self.dna.retirement_capacity:
            tail=pending[-1]
            if tail['sealed']:raise Fault('retirement_full') # Invalid/unexpected queue shape.
            tail['digest']=hashlib.sha256((tail['digest']+digest).encode()).hexdigest()
            tail['count']+=1;state['merges']+=1
        else:
            state['sequence']+=1
            pending.append(dict(sequence=state['sequence'],digest=digest,count=1,sealed=False))
        state['retired_events']+=1
        Agent.replace_memory(self,field,source,value,n)

    def prepare_emission(self,event):
        event['sealed']=True

    def before_request(self,n,tools):
        if self.dna.emission_phase == "after":
            self.last_emissions=[]
            return
        self.emit_pending(n,tools)

    def emission_room(self,tools):
        if self.dna.emission_phase == "after":
            return min(1,max(0,self.dna.max_calls-len(tools.calls)))
        return super().emission_room(tools)

    def emit_pending(self,n,tools):
        before=sum(e['count'] for e in self.retirement['pending'])
        try:super().before_request(n,tools)
        finally:
            after=sum(e['count'] for e in self.retirement['pending'])
            self.retirement['accepted_events']+=before-after

    def step(self,n,tools):
        if self._pending_maintenance is not None:
            raise ValueError('Finish maintenance before the next request')
        result=super().step(n,tools)
        if self.dna.emission_phase == 'after':self._pending_maintenance=(n,tools,result)
        state=self.retirement
        result['dissipation'].update(retired_events=state['retired_events'],accepted_events=state['accepted_events'],merges=state['merges'])
        return result

    def will_emit(self,n,tools):
        return n>=self.retirement['retry_after']

    def maintenance_due(self,n,tools):
        """Read-only scheduling hint; not a reservation or receipt from the sink."""
        self._validate_maintenance(n,tools)
        return bool(self.retirement['pending']
                    and self.emission_room(tools)>0 and self.will_emit(n,tools))

    def _validate_maintenance(self,n,tools):
        if self.dna.emission_phase != 'after':
            raise ValueError('Maintenance ticks require after-task emission')
        if (self._pending_maintenance is not None or getattr(self,'_tool_session',None) is not None
                or getattr(self,'_tool_session_failed',False)):
            raise ValueError('Active or failed request; finish or reload checkpoint')
        if type(n) is not int or n<=self.last_step:
            raise ValueError('Steps must be nonnegative and strictly increasing')
        if asdict(tools.dna)!=asdict(self.dna) or tools.calls or tools.cost:
            raise ValueError('Use fresh tools with the same DNA')
        if not callable(getattr(tools,'dissipate',None)):
            raise ValueError('Dissipative habitat required')

    def maintain(self,n,tools,checkpoint):
        """One explicit maintenance tick, sharing the monotonic request clock.

        No task reads or task predictor updates. The host schedules ticks.
        Discard this instance and reload after any persistence/emission failure.
        """
        self._validate_maintenance(n,tools)
        try:
            self.before_request(n,tools)
            self.last_step=n
            result=dict(n=n,kind='maintenance',task_executed=False,output=None,
                        help_requested=False,calls=tools.calls,cost=tools.cost)
            self._pending_maintenance=(n,tools,result)
            result=self.finish_request(n,tools,checkpoint)
            result['maintenance_complete']=not self.retirement['pending']
            return result
        except Exception:
            self._tool_session_failed=True
            raise

    def finish_request(self,n,tools,checkpoint):
        """Persist pending batches before exposing them to the external sink."""
        if self.dna.emission_phase != 'after' or self._pending_maintenance is None:
            raise ValueError('No deferred maintenance to finish')
        step,owned_tools,result=self._pending_maintenance
        if n!=step or tools is not owned_tools:raise ValueError('Mismatched request adapter')
        from pathlib import Path
        location=Path(checkpoint).resolve()
        root=tools.root.resolve()
        if location==root or root in location.parents or location==Path(tools.reservoir.path).resolve():
            raise ValueError('Checkpoint must be separate from habitat and reservoir')
        from .checkpoint import save_checkpoint, canonical, snapshot
        if self.retirement['pending'] and self.emission_room(tools)>0 and self.will_emit(n,tools):
            # Freeze the sole batch eligible for emission BEFORE its durable
            # checkpoint. New changes after a crash may only modify another slot.
            self.prepare_emission(self.retirement['pending'][0])
        durable_state=canonical(snapshot(self))
        save_checkpoint(self,checkpoint)
        # On any subsequent failure, recover from the durable checkpoint instead
        # of attempting to finish again on this partially advanced instance.
        self._pending_maintenance=None
        self.emit_pending(n,tools)
        # Compare the complete persistent state, not just tool-call counts:
        # predictors or backoff may change even without a successful emission.
        if canonical(snapshot(self)) != durable_state:
            save_checkpoint(self,checkpoint)
        state=self.retirement
        result['cost']=tools.cost
        result['dissipation']=dict(pending=len(state['pending']),accepted=state['accepted'],pressure=state['pressure'],
                                   receipts=self.last_emissions,retired_events=state['retired_events'],
                                   accepted_events=state['accepted_events'],merges=state['merges'])
        return result

class CompactReservoir(RetirementReservoir):
    def accept(self,stream,event):
        if type(event) is not dict or set(event)!= {'sequence','digest','count','sealed'} or type(event['count']) is not int or event['count']<1 or event['sealed'] is not True:
            raise Fault('invalid_compact_emission')
        # Parent validates the digest and sequence before using either. Include
        # represented count in its durable fingerprint to detect latest conflicts.
        if type(event['digest']) is not str or len(event['digest'])!=64 or any(c not in '0123456789abcdef' for c in event['digest']):
            raise Fault('invalid_compact_emission')
        digest=hashlib.sha256((str(event['count'])+':'+event['digest']).encode()).hexdigest()
        return super().accept(stream,dict(sequence=event['sequence'],digest=digest))
