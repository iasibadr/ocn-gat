"""Experimental one-step viability under explicit, caller-supplied error bounds.

No execution authority, reserve debit, physical units or stability guarantee.
Bounds apply to the declared affine/tanh model, not to an unknown environment.
"""
from dataclasses import dataclass
import math
import numpy as np


def vector(value, name):
    value=np.asarray(value,dtype=float)
    if value.shape!=(4,) or not np.isfinite(value).all():
        raise ValueError(name+' must contain four finite coordinates')
    return value


@dataclass(frozen=True)
class Envelope:
    mean: tuple
    lower: tuple
    upper: tuple
    jacobian: tuple


def transition_envelope(matrix,state,radius,*,bias=(0,0,0,0),model_error=(0,0,0,0),activation='linear'):
    """Enclose F(state+delta)+error for |delta|<=radius, |error|<=model_error.

    The 16 Jacobian entries describe local sensitivity. Finite interval propagation
    supplies the bound; using only J at the center would be insufficient for tanh.
    Floating point arithmetic is not a formally outward-rounded interval proof.
    """
    a=np.asarray(matrix,dtype=float)
    if a.shape!=(4,4) or not np.isfinite(a).all():raise ValueError('Finite 4x4 matrix required')
    z=vector(state,'state');r=vector(radius,'radius');b=vector(bias,'bias');e=vector(model_error,'model_error')
    if np.any(r<0) or np.any(e<0):raise ValueError('Uncertainty bounds must be nonnegative')
    if activation not in ('linear','tanh'):raise ValueError('Unsupported activation')
    with np.errstate(over='ignore',invalid='ignore'):
        center=a@z+b;spread=np.abs(a)@r
        lower=center-spread;upper=center+spread
    if not all(np.isfinite(v).all() for v in (center,spread,lower,upper)):
        raise ValueError('Nonfinite interval arithmetic')
    if activation=='tanh':
        mean=np.tanh(center);lower=np.tanh(lower);upper=np.tanh(upper)
        jacobian=(1-mean**2)[:,None]*a
    else:mean=center;jacobian=a
    with np.errstate(over='ignore',invalid='ignore'):
        lower=lower-e;upper=upper+e
    if not np.isfinite(lower).all() or not np.isfinite(upper).all():raise ValueError('Nonfinite error envelope')
    return Envelope(tuple(mean),tuple(lower),tuple(upper),tuple(map(tuple,jacobian)))


def admissible(envelope,minimum,maximum,*,reserve,cost_upper,reserve_floor,margin=0.):
    """Check a one-step state box and budget. Caller separately authorizes actions.

    cost_upper must include prediction/learning/checking cost if applicable. The
    function does not deduct anything or claim the bound is calibrated/guaranteed.
    """
    if type(envelope) is not Envelope:raise ValueError('Expected prediction envelope')
    lo=vector(envelope.lower,'lower');hi=vector(envelope.upper,'upper')
    minimum=vector(minimum,'minimum');maximum=vector(maximum,'maximum')
    if np.any(lo>hi) or np.any(minimum>maximum):raise ValueError('Inverted bounds')
    for v in (reserve,cost_upper,reserve_floor,margin):
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
            raise ValueError('Finite nonnegative reserve, cost, floor and margin required')
    if np.any(minimum+margin>maximum-margin):return False
    return bool(np.all(lo>=minimum+margin) and np.all(hi<=maximum-margin)
                and reserve-cost_upper>=reserve_floor)
