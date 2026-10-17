"""Opt-in decision-temperature feedback from bounded verified host history.

An exploration actuator, not a physical temperature, viability probability or
unified XTQT coordinate. Does not authorize actions or allocate probe budgets.
"""
from dataclasses import dataclass
import json

from .experience_memory import ExperienceMemory, label
from .reward_selection import finite


@dataclass(frozen=True)
class OutcomeTemperature:
    minimum: float = .05
    maximum: float = .5
    rate: float = .25
    window: int = 32

    def __post_init__(self):
        for name in ('minimum', 'maximum', 'rate'):
            finite(getattr(self, name), name)
        if not 0 < self.minimum <= self.maximum or not 0 < self.rate <= 1:
            raise ValueError('Positive ordered temperatures and rate in (0,1] required')
        if type(self.window) is not int or not 1 <= self.window <= 32:
            raise ValueError('History window must be 1..32')

    def read(self, memory, context):
        if type(memory) is not ExperienceMemory:
            raise ValueError('ExperienceMemory required')
        label(context)
        # One read snapshot. No auxiliary state: reloading or replaying the same
        # event cannot heat twice. Per-pair retention >=32 preserves this suffix.
        with memory.connect() as db:
            memory.metadata(db)
            rows = db.execute(
                'SELECT event_id,payload FROM outcomes WHERE context=? '
                'ORDER BY seq DESC LIMIT ?', (context, self.window)).fetchall()
        activity = 0.
        for _, payload in reversed(rows):
            success = json.loads(payload)['success']
            if type(success) is not bool:
                raise ValueError('Boolean verified outcome required')
            activity = (1-self.rate)*activity + self.rate*int(not success)
        value = (1-activity)*self.minimum + activity*self.maximum
        return dict(temperature=value, observations=len(rows),
                    latest_event_id=rows[0][0] if rows else None,
                    context=context, source='bounded_host_outcomes',
                    policy='outcome_temperature.v1', minimum=self.minimum,
                    maximum=self.maximum, rate=self.rate, window=self.window,
                    meaning='exploration_actuator_not_viability_or_kelvin')
