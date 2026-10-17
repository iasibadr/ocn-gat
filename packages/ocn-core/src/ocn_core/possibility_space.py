"""Bounded hypothetical quaternion trajectories; no tools, execution or learning.

Host-supplied action models are assumptions, including rewards and error bounds.
Only predicted terminal branches can be proposed. All outputs remain hypothetical.
"""
from dataclasses import dataclass
import math
import numpy as np
from .geometry_learning import BASIS
from .reward_selection import finite


def vector(value,name):
    a=np.asarray(value)
    if a.shape!=(4,) or a.dtype.kind not in 'fiu' or not np.isfinite(a).all():
        raise ValueError(name+' must contain four finite real coordinates')
    return a.astype(float,copy=True)


def product(p,q):return np.einsum('a,aij,j->i',p,BASIS,q)


def conditions(values,limit=32):
    if (type(values) not in (tuple,list) or len(values)>limit or
        any(type(v) is not str or not v.strip() or len(v)>128 for v in values) or
        len(set(values))!=len(values)):
        raise ValueError('Distinct bounded condition labels required')
    return frozenset(values)


@dataclass(frozen=True)
class ActionModel:
    action_id: str
    environment: tuple
    predicted_reward: float
    cost_upper: float
    terminal: bool = False
    left: tuple = (1.,0.,0.,0.)
    right: tuple = (1.,0.,0.,0.)
    amplitude: float = 1.
    plane: tuple = (0.,1.,0.,0.)
    parallel_gate: float = 0.
    perpendicular_gate: float = 0.
    injection: tuple = (0.,0.,0.,0.)
    error_bound: tuple = (0.,0.,0.,0.)
    requires: tuple = ()
    adds: tuple = ()
    removes: tuple = ()


def affine_model(action):
    """Convert two-sided Hamilton evolution plus membrane exchange to affine form."""
    if type(action) is not ActionModel:raise ValueError('ActionModel required')
    if type(action.action_id) is not str or not action.action_id or len(action.action_id)>128:
        raise ValueError('Bounded action identifier required')
    if type(action.terminal) is not bool:raise ValueError('Boolean terminal assumption required')
    conditions(action.requires)
    if conditions(action.adds)&conditions(action.removes):
        raise ValueError('A condition cannot be added and removed together')
    finite(action.predicted_reward,'predicted reward')
    if finite(action.cost_upper,'cost bound')<0:raise ValueError('Nonnegative cost bound required')
    if not 0<=finite(action.amplitude,'amplitude')<=1:raise ValueError('Amplitude must be in [0,1]')
    for gate in (action.parallel_gate,action.perpendicular_gate):
        if not 0<=finite(gate,'membrane gate')<=1:raise ValueError('Membrane gates must be in [0,1]')
    left=vector(action.left,'left');right=vector(action.right,'right');u=vector(action.plane,'plane')
    if any(abs(np.linalg.norm(q)-1)>1e-12 for q in (left,right,u)) or abs(u[0])>1e-12:
        raise ValueError('Unit rotations and pure unit imaginary plane required')
    environment=vector(action.environment,'environment');injection=vector(action.injection,'injection')
    error=vector(action.error_bound,'error bound')
    if np.any(error<0):raise ValueError('Nonnegative coordinate error bounds required')
    eye=np.eye(4);conjugate=right*np.array([1,-1,-1,-1])
    rotation=np.column_stack([product(product(left,v),conjugate) for v in eye])
    projection=(eye-np.column_stack([product(product(u,v),u) for v in eye]))/2
    membrane=action.parallel_gate*projection+action.perpendicular_gate*(eye-projection)
    matrix=(eye-membrane)@(action.amplitude*rotation)
    offset=membrane@environment+injection
    if not np.isfinite(offset).all():raise ValueError('Nonfinite affine offset')
    return matrix,offset,error


def explore(initial,actions,*,anchor_id,coordinate_contract,authorized,minimum,maximum,
            reserve,reserve_floor=0.,horizon=3,max_expansions=128,discount=1.,initial_conditions=(),
            decision_temperature=None):
    """Explore finite action sequences. Incomplete search never authorizes a winner.

    No external observation is created; anchor_id is a host-provided reference,
    not evidence verified by this function. Interval bounds are model-conditional
    floating-point bounds, not certified enclosures of the actual environment.
    """
    if decision_temperature is not None:
        if finite(decision_temperature,"decision temperature")<=0:
            raise ValueError("Positive decision temperature required")
    for label in (anchor_id,coordinate_contract):
        if type(label) is not str or not label.strip() or len(label)>256:raise ValueError('Explicit anchor and coordinate contract required')
    if type(actions) not in (list,tuple) or not 1<=len(actions)<=8:raise ValueError('One to eight action models required')
    if type(authorized) not in (set,frozenset) or any(type(a) is not str for a in authorized):
        raise ValueError('Explicit host authorization set required')
    if type(horizon) is not int or not 1<=horizon<=4:raise ValueError('Horizon must be 1..4')
    if type(max_expansions) is not int or not 1<=max_expansions<=512:raise ValueError('Expansion budget must be 1..512')
    if not 0<=finite(discount,'discount')<=1:raise ValueError('Discount must be in [0,1]')
    if not 0<=finite(reserve_floor,'reserve floor')<=finite(reserve,'reserve'):raise ValueError('Invalid reserve')
    state=vector(initial,'initial');low=vector(minimum,'minimum');high=vector(maximum,'maximum')
    if np.any(low>high) or np.any(state<low) or np.any(state>high):raise ValueError('Initial state outside declared viability box')
    initial_labels=conditions(initial_conditions,limit=64)
    vocabulary=set(initial_labels)
    prepared=[];names=set()
    for action in actions:
        matrix,offset,error=affine_model(action)
        if action.action_id in names:raise ValueError('Duplicate action model')
        vocabulary.update((*action.requires,*action.adds,*action.removes))
        if len(vocabulary)>64:raise ValueError('At most 64 distinct conditions allowed')
        names.add(action.action_id);prepared.append((action,matrix,offset,error))
    trace=[];best=None;best_reward=0.;incomplete=False

    def visit(mean,radius,path,reward,remaining,labels):
        nonlocal best,best_reward,incomplete
        for action,matrix,offset,error in prepared:
            if len(trace)>=max_expansions:incomplete=True;return
            sequence=path+[action.action_id]
            row=dict(path=sequence,status='predicted',admissible=False)
            trace.append(row)
            if action.action_id not in authorized:
                row['reason']='not_authorized';continue
            missing=set(action.requires)-labels
            if missing:
                row.update(reason='missing_predicted_preconditions',missing=sorted(missing));continue
            available=remaining-action.cost_upper
            if available<reserve_floor:
                row['reason']='reserve_constraint';continue
            with np.errstate(over='ignore',invalid='ignore'):
                future=matrix@mean+offset
                uncertainty=abs(matrix)@radius+error
                score=reward+(discount**len(path))*action.predicted_reward
            if not np.isfinite(future).all() or not np.isfinite(uncertainty).all() or not np.isfinite(score):
                raise ValueError('Nonfinite trajectory')
            row.update(state=future.tolist(),error_bound=uncertainty.tolist(),
                       remaining_reserve=available,predicted_return=float(score),terminal=action.terminal)
            if np.any(future-uncertainty<low) or np.any(future+uncertainty>high):
                row['reason']='predicted_viability_constraint';continue
            future_labels=(labels-set(action.removes))|set(action.adds)
            row.update(admissible=True,reason='model_admissible',predicted_conditions=sorted(future_labels))
            if action.terminal:
                preferable=(score>best_reward or (best is not None and score==best_reward and
                    (available,-len(sequence))>(best['remaining_reserve'],-len(best['path']))))
                if preferable:best=row.copy();best_reward=float(score)
            elif len(sequence)<horizon:
                visit(future,uncertainty,sequence,float(score),available,future_labels)
                if incomplete:return
    visit(state,np.zeros(4),[],0.,reserve,initial_labels)
    result=dict(status='incomplete' if incomplete else 'proposed' if best else 'abstained',
        action_id=None if incomplete or best is None else best['path'][0],
        proposal=None if incomplete else best,explored=trace,expansions=len(trace),
        anchor_id=anchor_id,coordinate_contract=coordinate_contract,
        initial_conditions=list(initial_conditions),initial_condition_status='host_declared',
        facts_created=False,actions_executed=0,scope='hypothetical_single_membrane')

    if decision_temperature is not None:
        result.update(action_id=None,proposal=None,decision_distribution=None)
        if not incomplete:
            # Max per first action prevents duplicate continuations increasing its mass.
            values={}
            for row in trace:
                if row['admissible'] and row['terminal']:
                    key=row['path'][0]
                    values[key]=max(values.get(key,-math.inf),row['predicted_return'])
            options=[(None,0.)]+sorted(values.items())
            peak=max(v for _,v in options)
            # Scaling before subtraction avoids overflow for opposite huge values.
            with np.errstate(over='ignore',under='ignore',invalid='raise'):
                weights=[math.exp(float((np.float64(v)/2-np.float64(peak)/2)
                    /decision_temperature*2)) for _,v in options]
            total=math.fsum(weights)
            probabilities=[w/total for w in weights]
            result.update(status='deliberating' if values else 'abstained',
                decision_distribution=[dict(action_id=a,predicted_value=v,probability=p)
                    for (a,v),p in zip(options,probabilities)],
                decision_entropy_nats=-math.fsum(p*math.log(p) for p in probabilities if p>0),
                decision_temperature=decision_temperature,
                probability_meaning='decision_preference_not_success_probability')
    return result
