"""Development-only stateless cadence rules using already persisted observations."""
from ocn_core import RepackingAgent

class CadenceAgent(RepackingAgent):
    cadence_mode = 'adaptive'

    def service_period(self):
        if self.cadence_mode.startswith('fixed'):
            return int(self.cadence_mode[5:])
        # Error EMA is observed task history, not a causal attribution or heat.
        error = max(self.errors.values(), default=0.)
        return 4 + round(28 * min(1., max(0., error)))

    def emission_decision(self, n, tools):
        if not self.retirement['pending'] or self.emission_room(tools) < 1:
            return False, None, None
        emit = (n - self.emission_state['last_attempt'] >= self.service_period()
                and n >= self.retirement['retry_after'])
        return emit, None, None
