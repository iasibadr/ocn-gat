"""Experimental online geometry selection extracted from GS-1.

Predict before observing. Coordinates are host-normalized X,t,Q,T, not physical
units or a complete cognitive state. No execution authority or viability guarantee.
"""
import numpy as np
from .reward_selection import finite

POLICIES = ('quaternion', 'diagonal_real', 'dense_real')
BASIS = np.array([
    np.eye(4),
    [[0,-1,0,0],[1,0,0,0],[0,0,0,-1],[0,0,1,0]],
    [[0,0,-1,0],[0,0,0,1],[1,0,0,0],[0,-1,0,0]],
    [[0,0,0,-1],[0,0,-1,0],[0,1,0,0],[1,0,0,0]],
], dtype=float)


class GeometryLearner:
    """Bounded in-memory predictor; one outstanding observation, fixed frame.

    All experts receive the same target after selection. Loss is prediction MSE,
    not operator reward. Tie order is POLICIES; no claim of calibrated confidence.
    """
    def __init__(self, units=1, *, learning_rate=.128, score_rate=.05):
        if type(units) is not int or not 1 <= units <= 64:
            raise ValueError('One to 64 units required')
        if not 0 < finite(learning_rate, 'learning rate') <= 1:
            raise ValueError('Learning rate must be in (0,1]')
        if not 0 < finite(score_rate, 'score rate') <= 1:
            raise ValueError('Score rate must be in (0,1]')
        self.units = units
        self.learning_rate = learning_rate
        self.score_rate = score_rate
        self._parameters = [np.tile([.1,0.,0.,0.], (units,1)),
                            np.full((units,4), .1), np.tile(.1*np.eye(4), (units,1,1))]
        self._scores = np.zeros(3)
        self._pending = None
        self.observations = 0

    def _coordinates(self, values):
        a = np.asarray(values)
        if a.shape != (self.units,4) or a.dtype.kind not in 'fiu':
            raise ValueError('Numeric coordinates must have shape (units,4)')
        a = a.astype(float, copy=True)
        if not np.isfinite(a).all() or np.any(np.abs(a)>1):
            raise ValueError('Explicitly normalized finite coordinates in [-1,1] required')
        return a

    def _matrices(self):
        q, d, full = self._parameters
        return [np.einsum('na,aij->nij', q, BASIS),
                np.einsum('ni,ij->nij', d, np.eye(4)), full]

    def predict(self, coordinates):
        if self._pending is not None:
            raise RuntimeError('Observe or discard the pending prediction first')
        x = self._coordinates(coordinates)
        matrices = self._matrices()
        outputs = [np.tanh(np.einsum('nij,nj->ni', m, x)) for m in matrices]
        chosen = int(np.argmin(self._scores))
        self._pending = (x, outputs, chosen)
        jacobian = (1-outputs[chosen]**2)[:,:,None]*matrices[chosen]
        return dict(policy=POLICIES[chosen], prediction=outputs[chosen].copy(),
                    sensitivities=jacobian.copy(), past_losses=self._scores.copy(),
                    observations=self.observations, uncertainty='uncalibrated')

    def observe(self, coordinates):
        if self._pending is None:
            raise RuntimeError('Prediction required before observation')
        target = self._coordinates(coordinates)
        x, outputs, chosen = self._pending
        losses = np.array([np.mean((output-target)**2) for output in outputs])
        denominator = .1 + np.sum(x*x, axis=1)
        updated = []
        for index, (parameters, output) in enumerate(zip(self._parameters, outputs)):
            error = (output-target)*(1-output**2)
            if index == 0:
                jacobian = np.einsum('aij,nj->nai', BASIS, x)
                gradient = np.einsum('ni,nai->na', error, jacobian)/denominator[:,None]
            elif index == 1:
                gradient = error*x/denominator[:,None]
            else:
                gradient = np.einsum('ni,nj->nij', error,x)/denominator[:,None,None]
            candidate = parameters-self.learning_rate*gradient
            axes = (1,2) if index == 2 else 1
            norms = np.linalg.norm(candidate,axis=axes)
            factor = np.minimum(1., (2. if index == 0 else 4.)/np.maximum(norms,1e-12))
            candidate *= factor[:,None,None] if index == 2 else factor[:,None]
            if not np.isfinite(candidate).all():
                raise ValueError('Nonfinite learning update')
            updated.append(candidate)
        self._parameters = updated
        self._scores = (1-self.score_rate)*self._scores+self.score_rate*losses
        self.observations += 1
        self._pending = None
        return dict(policy=POLICIES[chosen], loss=float(losses[chosen]),
                    expert_losses=dict(zip(POLICIES, map(float,losses))))

    def discard(self):
        """Missing observations must not become fabricated zero-loss targets."""
        if self._pending is None:
            raise RuntimeError('No pending prediction')
        self._pending = None
