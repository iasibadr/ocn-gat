"""Experimental in-process bridge from possibilities to host-verified experience.

Not enabled by GAT. Trusted synchronous host, no crash recovery or global budget.
Terminal actions only; declared transitions are not learned. Optional bounded
outcome feedback regulates decision temperature; its mapping is not learned.
"""
from copy import deepcopy
from dataclasses import asdict
import random
import uuid
from .experience_memory import ExperienceMemory,label
from .experienced_possibilities import explore_from_experience
from .reward_selection import finite
from .possibility_space import vector,conditions,affine_model
from .viability import transition_envelope,admissible
from .probe_budget import PersistentProbeBudget
from .adaptive_temperature import OutcomeTemperature


def observation(value):
    value=deepcopy(value)
    if type(value) is not dict or set(value)!={'anchor_id','context','state','authorized','conditions'}:
        raise ValueError('Exact host observation required')
    label(value['anchor_id']);label(value['context']);vector(value['state'],'observed state')
    conditions(value['conditions'],limit=64)
    if type(value['authorized']) not in (set,frozenset):raise ValueError('Authorization set required')
    for name in value['authorized']:label(name)
    return value


class ExperiencedCycle:
    def __init__(self,memory,*,reserve,seed=0,probe_budget=0,persistent_probes=None):
        if type(memory) is not ExperienceMemory:raise ValueError('ExperienceMemory required')
        if finite(reserve,'reserve')<0:raise ValueError('Nonnegative reserve required')
        if type(seed) is not int:raise ValueError('Integer seed required')
        if type(probe_budget) is not int or not 0<=probe_budget<=64:raise ValueError('Probe budget must be 0..64')
        if persistent_probes is not None:
            if type(persistent_probes) is not PersistentProbeBudget or probe_budget!=0:
                raise ValueError('Use either an explicit persistent allowance or a local probe budget')
            persistent_probes.check_binding(memory,persistent_probes.expected['coordinate_contract'])
        self.persistent_probes=persistent_probes
        self.probes_remaining=probe_budget if persistent_probes is None else persistent_probes.remaining()
        self.memory=memory;self.reserve=float(reserve);self.rng=random.Random(seed)
        self.pending=None;self.halted=False

    def retry_record(self):
        """Retry only a verified pending write; never execute the action again."""
        if self.pending is None:raise ValueError('No verified write pending')
        self.memory.record(**self.pending)
        self.pending=None
        return dict(status='recorded',actions_executed=0)

    def step(self,actions,*,observe,execute,verify,decision_temperature=None,
             coordinate_contract,minimum,maximum,reserve_floor=0.,minimum_observations=3,
             temperature_policy=None):
        """Host callbacks must enforce permissions and preconditions at execution.

        observe() returns anchor_id, context, state, authorized and conditions.
        execute(action_id, observation, event_id) returns an opaque receipt.
        verify(before, action_id, receipt, after) returns success, quality,
        interventions, cost, evidence_id. Evidence authenticity is host-owned.
        All costs here use one explicit host unit; total metabolism is not measured.
        """
        if self.halted:raise RuntimeError('Unresolved effect or cost breach; cycle halted')
        if self.pending is not None:raise RuntimeError('Verified experience must be recorded first')
        if not all(callable(f) for f in (observe,execute,verify)):raise ValueError('Host callbacks required')
        if temperature_policy is not None:
            if type(temperature_policy) is not OutcomeTemperature or decision_temperature is not None:
                raise ValueError('Choose a fixed temperature or an OutcomeTemperature policy')
        elif decision_temperature is None:
            raise ValueError('Explicit fixed temperature or policy required')
        if self.persistent_probes is not None:
            self.persistent_probes.check_binding(self.memory,coordinate_contract)
            self.probes_remaining=self.persistent_probes.remaining()
        before=observation(observe())
        regulation=None
        if temperature_policy is not None:
            regulation=temperature_policy.read(self.memory,before['context'])
            decision_temperature=regulation['temperature']
        plan=explore_from_experience(self.memory,before['context'],before['state'],actions,
            authorized=before['authorized'],decision_temperature=decision_temperature,
            minimum_observations=minimum_observations,anchor_id=before['anchor_id'],
            coordinate_contract=coordinate_contract,minimum=minimum,maximum=maximum,
            reserve=self.reserve,reserve_floor=reserve_floor,initial_conditions=before['conditions'])
        if regulation is not None:
            plan['temperature_regulation']=regulation
        # Unknown is not assigned a fabricated utility. Explicit probes use
        # separate admission and a finite budget, while retaining the null estimate.
        probe_candidates=[]
        if self.probes_remaining:
            estimates={e['action_id']:e for e in plan['reward_estimates']}
            for action in actions:
                estimate=estimates[action.action_id]
                if estimate['eligible'] or action.action_id not in before['authorized']:continue
                if not set(action.requires)<=set(before['conditions']):continue
                matrix,offset,error=affine_model(action)
                envelope=transition_envelope(matrix,before['state'],(0,)*4,bias=offset,model_error=error)
                if admissible(envelope,minimum,maximum,reserve=self.reserve,
                              cost_upper=action.cost_upper,reserve_floor=reserve_floor):
                    probe_candidates.append((estimate['observations'],action,envelope))
        selection='experience_distribution';probe_envelope=None
        if probe_candidates:
            _,model,probe_envelope=min(probe_candidates,key=lambda row:row[0])
            choice=model.action_id;selection='authorized_probe'
            if self.persistent_probes is not None:
                self.probes_remaining=self.persistent_probes.reserve()['remaining']
            else:self.probes_remaining-=1
        else:
            distribution=plan.get('decision_distribution')
            if not distribution:return dict(status=plan['status'],plan=plan,actions_executed=0)
            choice=self.rng.choices(distribution,weights=[r['probability'] for r in distribution],k=1)[0]['action_id']
            if choice is None:return dict(status='abstained',plan=plan,actions_executed=0)
            model=next(a for a in actions if a.action_id==choice)
        event_id='cycle-'+uuid.uuid4().hex
        # Reserve the declared upper cost before any effect. Unresolved effects
        # retain this debit and halt; do not make an automatic retry possible.
        self.reserve-=model.cost_upper
        event=dict(event_id=event_id,action=choice,selection=selection,probes_remaining=self.probes_remaining,probe_envelope=asdict(probe_envelope) if probe_envelope is not None else None,plan=plan,before=deepcopy(before),execution_attempts=1,actions_executed=None)
        try:
            receipt=execute(choice,deepcopy(before),event_id)
            after=observation(observe())
            verdict=verify(deepcopy(before),choice,receipt,deepcopy(after))
            if type(verdict) is not dict or set(verdict)!={'success','quality','interventions','cost','evidence_id'}:
                raise ValueError('Exact host verdict required')
            label(verdict['evidence_id'])
            if type(verdict['success']) is not bool:raise ValueError('Boolean observed success required')
            if not 0<=finite(verdict['quality'],'quality')<=1:raise ValueError('Quality outside [0,1]')
            if type(verdict['interventions']) is not int or not 0<=verdict['interventions']<=1000000:
                raise ValueError('Invalid intervention count')
            if finite(verdict['cost'],'cost')<0:raise ValueError('Negative cost')
        except Exception as exc:
            self.halted=True
            return dict(**event,status='unresolved',error=type(exc).__name__+': '+str(exc),reserve=self.reserve,feedback_written=False)
        self.reserve+=model.cost_upper-verdict['cost']
        breach=verdict['cost']>model.cost_upper or self.reserve<reserve_floor
        self.halted=breach
        self.pending=dict(event_id=event_id,context=before['context'],action=choice,
            **{k:verdict[k] for k in ('success','quality','interventions','cost')})
        event.update(after=after,verdict=verdict,reserve=self.reserve,actions_executed=1)
        try:self.retry_record()
        except Exception as exc:
            return dict(**event,status='memory_pending',error=type(exc).__name__+': '+str(exc),feedback_written=False,cost_breach=breach)
        return dict(**event,status='cost_breach' if breach else 'observed',feedback_written=True)
