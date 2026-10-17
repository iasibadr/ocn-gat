"""Explicit local-first policy; model fallback only after a conclusive local miss."""
import json
from pathlib import Path
from .candidate_evaluation import validate_suite,canonical
from .local_repair import local_repair
from .bridge_repair import repair,write


def hybrid_repair(instance,contract,suite,proposer,output,*,limit=8,observe_runtime=False,share_acceptance_feedback=False,preserve_acceptance=False):
    from .gat import load
    if type(contract) is not str or not contract.strip() or len(contract.encode())>4096:
        raise ValueError('Bounded operator contract required')
    if type(limit) is not int or not 1<=limit<=8:raise ValueError('Candidate limit must be 1..8')
    if type(observe_runtime) is not bool or type(share_acceptance_feedback) is not bool:
        raise ValueError('Boolean observation and feedback permissions required')
    if type(preserve_acceptance) is not bool:raise ValueError('Boolean acceptance preservation required')
    validate_suite(suite);suite=json.loads(canonical(suite))
    root,config=load(instance);output=Path(output).resolve()
    for protected in (root,Path(config['habitat']).resolve()):
        if output==protected or protected in output.parents or output in protected.parents:
            raise ValueError('Audit must be outside instance and habitat')
    output.mkdir(exist_ok=False)
    write(output/'policy.json',dict(policy='local_then_one_designer',candidate_limit=limit,
        maximum_designer_calls=1,observe_runtime=observe_runtime,share_acceptance_feedback=share_acceptance_feedback,preserve_acceptance=preserve_acceptance))
    try:
        local=local_repair(root,suite,output/'local',limit=limit,preserve_acceptance=preserve_acceptance)
        if local['status']=='no_passing_candidate':
            designed=repair(root,contract,suite,proposer,output/'designer',observe_runtime=observe_runtime,
                            share_acceptance_feedback=share_acceptance_feedback,preserve_acceptance=preserve_acceptance)
            result=dict(status=designed['status'],route='local_then_designer',local=local,designer=designed,
                        designer_calls=designed['designer_calls'])
        else:
            # A successful local repair, an already valid agent, or an adoption
            # not made is terminal. Exceptions are never interpreted as misses.
            result=dict(status=local['status'],route='local_only',local=local,designer_calls=0)
        write(output/'result.json',result);return result
    except Exception as exc:
        write(output/'failure.json',dict(error_type=type(exc).__name__,status='failed_or_uncertain',
            automatic_retry=False,inspect_instance_before_retry=True))
        raise
