"""Bounded two-window mean-shift diagnostic; no policy or memory mutation.

Not ADWIN. The false-alert bound assumes an independent stationary [0,1] stream
and at most max_checks comparisons for this monitor. It does not cover repeated
resets, multiple monitors, dependent outcomes or changes in context/action mix.
"""
from collections import deque
import math
from .reward_selection import finite


class ChangeMonitor:
    def __init__(self, *, half_window=32, max_checks=512, alpha=.05):
        if type(half_window) is not int or not 2<=half_window<=256:
            raise ValueError('Half-window must be 2..256')
        if type(max_checks) is not int or not 1<=max_checks<=1000000:
            raise ValueError('Check budget must be 1..1000000')
        if not 0<finite(alpha,'alpha')<1:raise ValueError('Alpha must be in (0,1)')
        self.half_window=half_window;self.max_checks=max_checks;self.alpha=alpha
        self.values=deque(maxlen=2*half_window);self.checks=0;self.observations=0
        self.threshold=math.sqrt(math.log(2*max_checks/alpha)/half_window)

    def observe(self,value):
        if not 0<=finite(value,'observed score')<=1:raise ValueError('Score must be in [0,1]')
        if self.checks>=self.max_checks:
            return dict(status='exhausted',detected=None,checks=self.checks,observations=self.observations)
        self.values.append(float(value));self.observations+=1
        if len(self.values)<2*self.half_window:
            return dict(status='warming',detected=None,checks=self.checks,observations=self.observations)
        self.checks+=1;values=list(self.values);n=self.half_window
        earlier=math.fsum(values[:n])/n;recent=math.fsum(values[n:])/n
        gap=recent-earlier;detected=abs(gap)>self.threshold
        return dict(status='assessed',detected=detected,checks=self.checks,
                    observations=self.observations,earlier_mean=earlier,recent_mean=recent,
                    mean_shift=gap,threshold=self.threshold,
                    direction=('improved' if gap>0 else 'degraded') if detected else None,
                    scope='mean_shift_not_cause_or_viability',policy_changed=False)
