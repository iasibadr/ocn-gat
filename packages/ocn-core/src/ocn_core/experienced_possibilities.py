"""Observed reward estimates for one-step hypothetical decisions.

The trusted host owns the memory, action meanings, context and model contracts.
No feedback is written and no prediction is promoted to an observation.
"""
from dataclasses import replace
from .experience_memory import ExperienceMemory, label
from .possibility_space import affine_model, explore
from .reward_selection import finite


def explore_from_experience(memory, context, initial, actions, *, authorized,
                            decision_temperature, minimum_observations=3,
                            success_weight=1., quality_weight=0.,
                            intervention_penalty=0., **constraints):
    """Value terminal actions using matching observed outcomes, never manual rewards.

    One-step only: a mission-level reward cannot be credited to every intermediate
    step. Call under the host's memory lock when concurrent writers are possible;
    separate estimate reads do not constitute a cross-action SQLite snapshot.
    Temperature remains explicitly supplied, not learned or urgency-calibrated.
    """
    if type(memory) is not ExperienceMemory:raise ValueError('ExperienceMemory required')
    label(context)
    if type(minimum_observations) is not int or not 1<=minimum_observations<=32:
        raise ValueError('Observation minimum must be 1..32')
    if type(actions) not in (list,tuple) or not 1<=len(actions)<=8:
        raise ValueError('One to eight terminal models required')
    if (type(authorized) not in (set,frozenset) or
        any(type(a) is not str for a in authorized)):raise ValueError('Authorization set required')
    if finite(decision_temperature,'decision temperature')<=0:raise ValueError('Positive temperature required')
    for w in (success_weight,quality_weight,intervention_penalty):
        if finite(w,'reward weight')<0:raise ValueError('Nonnegative weights required')
    if success_weight==quality_weight==0:raise ValueError('Positive utility weight required')
    if 'horizon' in constraints:raise ValueError('Observed terminal valuation requires horizon one')
    valued=[];eligible=set();estimates=[]
    for action in actions:
        affine_model(action)
        if not action.terminal:raise ValueError('Observed terminal valuation requires terminal models')
        estimate=memory.estimate(context,action.action_id,success_weight=success_weight,
            quality_weight=quality_weight,intervention_penalty=intervention_penalty)
        known=estimate['observations']>=minimum_observations
        if known:eligible.add(action.action_id)
        # Unknown zero is only an internal placeholder; authorization excludes it.
        valued.append(replace(action,predicted_reward=estimate['expected_return'] if known else 0.))
        estimates.append(dict(action_id=action.action_id,eligible=known,**estimate))
    result=explore(initial,valued,authorized=authorized & eligible,horizon=1,
                   decision_temperature=decision_temperature,**constraints)
    result.update(value_source='host_observed_reward_ewma',experience_contract=memory.contract_id,
                  experience_context=context,reward_estimates=estimates,
                  minimum_observations=minimum_observations,
                  reward_weights=dict(success_weight=success_weight,quality_weight=quality_weight,
                                      intervention_penalty=intervention_penalty),
                  feedback_written=False)
    return result
