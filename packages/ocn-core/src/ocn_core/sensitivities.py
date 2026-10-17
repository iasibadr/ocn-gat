"""Local derivatives of the frozen predictor, not causal derivatives of a world."""
import math
import numpy as np
from .controller import left


def prediction_jacobian(model,action,*,input_order=(0,1,2,3),prior_jacobian=None,conjugate_output=False):
    """d[C (model(P u)[action] + A u)] / du with P and weights fixed.

    C is identity, or diag(1,-1,-1,-1) for output conjugation. Biases
    disappear. The caller supplies A for any nonconstant prediction prior.
    This excludes clipping, chart selection, action argmin and environment effects.
    """
    if type(action) is not int or not 0<=action<4:raise ValueError('Invalid action')
    if len(input_order)!=4 or any(type(i) is not int for i in input_order) or set(input_order)!={0,1,2,3}:
        raise ValueError('Input order must be a permutation')
    if type(conjugate_output) is not bool:raise ValueError('Invalid conjugation flag')
    matrix=model.w[action].copy() if model.policy=='classical_learner' else left(model.a[action])
    result=matrix@np.eye(4)[list(input_order)]
    if prior_jacobian is not None:
        prior=np.asarray(prior_jacobian,dtype=float)
        if prior.shape!=(4,4) or not np.isfinite(prior).all():raise ValueError('Invalid prior Jacobian')
        result=result+prior
    if not np.isfinite(result).all():raise ValueError('Nonfinite Jacobian')
    if conjugate_output:result=np.diag([1.,-1.,-1.,-1.])@result
    return result


def action_entropy(probabilities):
    """Shannon entropy in nats of the declared action distribution; no heat units."""
    p=np.asarray(probabilities,dtype=float)
    if p.ndim!=1 or not len(p) or not np.isfinite(p).all() or np.any(p<0) or abs(float(p.sum())-1)>1e-12:
        raise ValueError('Expected a finite probability distribution')
    return -math.fsum(float(v)*math.log(float(v)) for v in p if v>0)
