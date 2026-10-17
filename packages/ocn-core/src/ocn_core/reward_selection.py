"""Experimental reward-first selection under host-defined viability constraints.

Pure planning: does not execute actions, debit budgets or certify reward forecasts.
"""
from dataclasses import dataclass
import math
from .viability import Envelope,admissible


def finite(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(name+' must be finite')
    return value


def discounted_return(rewards,discount):
    finite(discount,'discount')
    if not 0<=discount<=1:raise ValueError('Discount must be in [0,1]')
    if type(rewards) not in (tuple,list) or not 1<=len(rewards)<=256:raise ValueError('Bounded reward horizon required')
    for value in rewards:finite(value,'reward')
    try:result=math.fsum(discount**i*r for i,r in enumerate(rewards))
    except OverflowError as exc:raise ValueError('Return overflow') from exc
    return finite(result,'return')


@dataclass(frozen=True)
class ActionForecast:
    action_id: str
    envelope: Envelope
    expected_return: float
    cost_upper: float


def select_action(candidates,*,authorized,minimum,maximum,reserve,reserve_floor,
                  abstention_return=0.,margin=0.):
    """Maximize predicted return, never return/cost, within declared constraints.

    Ties retain abstention first, otherwise caller order. Forecast provenance and
    reward criteria must be controlled by the host, not by candidate code. The
    envelope and reserve check are one-step; expected return may include a longer
    horizon but that does not imply multi-step viability has been established.
    """
    if type(candidates) not in (list,tuple) or len(candidates)>64:raise ValueError('At most 64 forecasts required')
    if type(authorized) not in (set,frozenset) or any(type(a) is not str or not a for a in authorized):
        raise ValueError('Host authorization set required')
    finite(abstention_return,'abstention return')
    seen=set();chosen=None;best=abstention_return;rows=[]
    for candidate in candidates:
        if type(candidate) is not ActionForecast:raise ValueError('Expected action forecast')
        key=candidate.action_id
        if type(key) is not str or not key or len(key)>128 or key in seen:raise ValueError('Unique bounded action identifiers required')
        seen.add(key);finite(candidate.expected_return,'expected return')
        viable=admissible(candidate.envelope,minimum,maximum,reserve=reserve,
            cost_upper=candidate.cost_upper,reserve_floor=reserve_floor,margin=margin)
        reason='not_authorized' if key not in authorized else 'not_viable' if not viable else 'eligible'
        rows.append(dict(action_id=key,reason=reason,expected_return=candidate.expected_return,cost_upper=candidate.cost_upper))
        if reason=='eligible' and candidate.expected_return>best:
            chosen=key;best=candidate.expected_return
    return dict(action_id=chosen,abstained=chosen is None,expected_return=best,
                criterion='maximum_expected_return_subject_to_constraints',assessments=rows)
