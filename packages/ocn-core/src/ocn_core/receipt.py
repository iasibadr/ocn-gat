"""Latest task receipt. Trusted local integrity, not exactly-once network delivery."""
import copy
import re
from .task import TaskSpec

FORMAT='ocn.task-checkpoint.v1'

def validate_request_id(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{32}',value) is None:
        raise ValueError('Request ID must be 32 lowercase hexadecimal characters')

def validate_receipt(receipt,agent):
    def exact(obj,keys):
        if type(obj) is not dict or set(obj)!=set(keys):raise ValueError('Invalid task receipt fields')
    exact(receipt,('request_id','step','identity','policy','task','outcome'))
    validate_request_id(receipt['request_id'])
    if type(receipt['step']) is not int or not 0<=receipt['step']<=agent.last_step:
        raise ValueError('Invalid receipt step')
    if receipt['identity']!=agent.identity or receipt['policy']!=agent.policy:
        raise ValueError('Receipt identity mismatch')
    exact(receipt['task'],('operation','sources'))
    if type(receipt['task']['sources']) is not list:raise ValueError('Invalid receipt sources')
    task=TaskSpec(receipt['task']['operation'],tuple(receipt['task']['sources']))
    if not set(task.sources)<=set(agent.dna.source_ids):raise ValueError('Receipt exceeds DNA')
    outcome=receipt['outcome'];exact(outcome,('done','refused','answer','error'))
    if type(outcome['done']) is not bool or type(outcome['refused']) is not bool:
        raise ValueError('Invalid receipt outcome flags')
    if not outcome['done']:
        if outcome['refused'] or outcome['answer'] is not None or outcome['error'] is not None:
            raise ValueError('Invalid unfinished receipt')
    elif outcome['refused']:
        if (outcome['answer'] is not None or type(outcome['error']) is not str
                or not 1<=len(outcome['error'])<=128 or outcome['error'] in ('schema','not_found','unavailable')):
            raise ValueError('Invalid refusal receipt')
    elif type(outcome['answer']) is not int or outcome['error'] is not None:
        raise ValueError('Invalid answer receipt')
    return receipt

def receipt_for_session(session):
    error=next((session.terminal_errors[s] for s in session.task.sources if s in session.terminal_errors),None) if session.refused else None
    receipt=dict(request_id=session.request_id,step=session.step,identity=session.agent.identity,
        policy=session.agent.policy,task=dict(operation=session.task.operation,sources=list(session.task.sources)),
        outcome=dict(done=session.done,refused=session.refused,answer=session.answer,error=error))
    return validate_receipt(receipt,session.agent)

def recover_task_receipt(source,expected_dna,expected_policy,*,request_id,step,task):
    """Read a historical outcome with caller-supplied expected identity and task.

    No task tools or model calls. Emission reconciliation is a separate operation.
    Raises on absence or conflict; never guesses or executes a replacement task.
    """
    validate_request_id(request_id)
    if type(step) is not int or step<0 or type(task) is not TaskSpec:
        raise ValueError('Expected task and nonnegative step required')
    from .checkpoint import load_checkpoint
    agent=load_checkpoint(source,expected_dna,expected_policy)
    receipt=getattr(agent,'_task_receipt',None)
    if receipt is None:raise ValueError('No durable task receipt')
    expected=dict(operation=task.operation,sources=list(task.sources))
    if receipt['request_id']!=request_id or receipt['step']!=step or receipt['task']!=expected:
        raise ValueError('Task receipt request conflict')
    return copy.deepcopy(receipt)
