"""Explicit maintained invocation; no daemon, hidden retry or new permissions."""
import json
from .application import locked, lifecycle
from .candidate_evaluation import canonical,PreExecutionAcceptanceError
from . import maintenance_policy


def run_maintained(instance,*,question=None,repair_on_failure=False,record=False,feedback_scope='mission',
                   learned_models=None,feedback_rubric=None,minimum_observations=3):
    if type(record) is not bool:raise ValueError('Boolean recording flag required')
    if learned_models is not None:
        from .run_feedback import validate_selection
        validate_selection(learned_models,feedback_rubric,minimum_observations,None)
        record=True
    selection=dict(learned_models=learned_models,feedback_rubric=feedback_rubric,minimum_observations=minimum_observations)
    if feedback_scope not in ('mission','document_versions'):raise ValueError('Unknown feedback scope')
    if feedback_scope!='mission' and not record:raise ValueError('Version feedback scope requires recording')
    from .gat import load,run,ISOLATED_FORMAT,BROKERED_FORMAT
    if type(repair_on_failure) is not bool:raise ValueError('Boolean repair trigger required')
    root,_=load(instance)
    with locked(root):
        root,config=load(root)
        if lifecycle(root)!='active':raise RuntimeError('Instance is paused or uninitialized')
        if config['format'] not in (ISOLATED_FORMAT,BROKERED_FORMAT):raise ValueError('Maintained execution requires isolation')
        if learned_models is not None and config['format']==BROKERED_FORMAT:
            from .run_feedback import check_broker_models
            check_broker_models(config,learned_models)
        policy=json.loads(canonical(maintenance_policy.read(root)))
        if policy['authority']!=maintenance_policy.authority(config):raise ValueError('Maintenance authority changed')
        preserve=policy.get('preserve_acceptance',False)
        suite=policy['suite']
        if preserve and config.get('evolution'):
            from .cumulative_adoption import read_retained,combine
            suite=combine(read_retained(root,config['evolution']['suite_sha256']),suite)
    scope=('configured and retained cases at entry and execution; no general correctness guarantee'
           if preserve else 'exact configured suite; no general correctness guarantee')
    if config['format']==BROKERED_FORMAT:
        scope+='; model request contract only, not answer correctness'
    if repair_on_failure:
        try:
            answer=run(root,question=question,acceptance_suite=suite,
                       expected_authority=policy['authority'],preserve_acceptance=preserve,record=record,feedback_scope=feedback_scope,**selection)
        except PreExecutionAcceptanceError as exc:
            # An execution timeout/crash is not a known behavioral mismatch.
            # Never interpret a mission failure as authorization to repeat it.
            if not exc.conclusive:raise
        else:
            return dict(**answer,maintenance_cycle=None,
                        maintenance_result=dict(status='not_needed',designer_calls=0),
                        acceptance_scope=scope)
    # tick owns its durable budget and candidate adoption controls. Exceptions
    # propagate; an uncertain repair never becomes a retry of the mission.
    maintenance=maintenance_policy.tick(root)
    if maintenance['result']['status'] not in ('adopted','already_accepted'):
        raise RuntimeError('Maintenance did not establish an accepted integration')
    # Recheck actual pinned bytes under the execution lock: another maintenance
    # cycle/adoption may have occurred since tick returned. Never rely on its
    # historical status alone to authorize execution of today's code.
    answer=run(root,question=question,acceptance_suite=suite,
               expected_authority=policy['authority'],preserve_acceptance=preserve,record=record,feedback_scope=feedback_scope,**selection)
    return dict(**answer,maintenance_cycle=maintenance['cycle'],
                maintenance_result=maintenance['result'],
                acceptance_scope=scope)
