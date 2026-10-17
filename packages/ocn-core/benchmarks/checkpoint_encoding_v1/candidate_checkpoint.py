"""Versioned JSON checkpoints for a trusted single-writer local store.

SHA256 detects accidental corruption, not malicious modification or rollback.
No pickle, dynamic imports, or executable state is accepted.
"""
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import numpy as np
from .controller import Agent, DNA, POLICIES

MAX_BYTES = 1_048_576
VERSION = 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def exact(obj, keys):
    if type(obj) is not dict or set(obj) != set(keys):
        raise ValueError('Invalid checkpoint fields')


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid checkpoint integer')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid checkpoint number')
    return value


def filename(value):
    if type(value) is not str or not value or len(value) > 4096 or Path(value).name != value or value in ('.','..','directory.json','schemas.json') or '\x00' in value:
        raise ValueError('Invalid checkpoint path')
    return value


def restore_predictor(data,model):
    exact(data, ('a','w','b'))
    for name,shape in (('a',(4,4)),('w',(4,4,4)),('b',(4,4))):
        raw = data[name]
        # Reject booleans and strings instead of silently coercing them.
        def numeric_tree(v):
            if type(v) is list:return all(numeric_tree(x) for x in v)
            return type(v) in (int,float) and math.isfinite(v)
        if not numeric_tree(raw):raise ValueError('Invalid predictor numbers')
        array = np.array(raw,dtype=float)
        if array.shape != shape or not np.isfinite(array).all():
            raise ValueError('Invalid predictor dimensions')
        setattr(model,name,array)


def snapshot(agent):
    if getattr(agent, "_tool_session", None) is not None or getattr(agent, "_tool_session_failed", False):
        raise ValueError("Cannot snapshot an active or failed tool session")
    result = dict(version=VERSION, dna=asdict(agent.dna), identity=agent.identity,
                policy=agent.policy, paths=agent.paths, descriptors=agent.descriptors,
                temperature=agent.temperature, last_refresh=agent.last_refresh,
                last_cost=agent.last_cost, errors=agent.errors, last_step=agent.last_step,
                predictor={name:getattr(agent.model,name).tolist() for name in ('a','w','b')},
                rng=agent.rng.getstate())
    if hasattr(agent, 'retirement'):
        result.update(version=3 if "retired_events" in agent.retirement else 2, retirement=agent.retirement)
    if hasattr(agent,'cell_models') and (agent.cell_models or agent.cell_temperatures):
        result['cells']=dict(models={s:{n:getattr(m,n).tolist() for n in ('a','w','b')} for s,m in agent.cell_models.items() if s!=agent.dna.source_ids[0]},temperatures=agent.cell_temperatures)
        result['version']=4
    if hasattr(agent,'emission_state'):
        result['emission']=dict(state=agent.emission_state,predictor={n:getattr(agent.emission_model,n).tolist() for n in ('a','w','b')})
        from .repacking import RepackingDNA
        result['version']=6 if isinstance(agent.dna,RepackingDNA) else 5
    return result


def restore(payload, expected_dna, expected_policy):
    from .dissipation import DissipativeDNA, DissipativeAgent
    from .compact import CompactDNA, CompactAgent
    from .scheduled import ScheduledDNA,ScheduledAgent
    from .repacking import RepackingDNA,RepackingAgent
    repacking=isinstance(expected_dna,RepackingDNA)
    scheduled=isinstance(expected_dna,ScheduledDNA)
    compact = isinstance(expected_dna, CompactDNA)
    dissipative = isinstance(expected_dna, DissipativeDNA)
    cells=compact and (expected_dna.learning_scope=="source" or expected_dna.temperature_scope=="source")
    exact(payload, ('version','dna','identity','policy','paths','descriptors','temperature',
                    'last_refresh','last_cost','errors','last_step','predictor','rng') + (('retirement',) if dissipative else ()) + (('cells',) if cells else ()) + (('emission',) if scheduled else ()))
    if type(payload['version']) is not int or payload['version'] != (6 if repacking else 5 if scheduled else 4 if cells else 3 if compact else 2 if dissipative else VERSION):
        raise ValueError('Unsupported checkpoint version')
    if expected_policy not in POLICIES or payload['policy'] != expected_policy:
        raise ValueError('Checkpoint policy mismatch')
    if canonical(payload['dna']) != canonical(asdict(expected_dna)):
        raise ValueError('Checkpoint DNA mismatch')
    sources = expected_dna.source_ids
    for field in ('paths','descriptors','last_refresh','last_cost','errors'):
        exact(payload[field], sources)
    paths = {s:filename(payload['paths'][s]) for s in sources}
    agent = (RepackingAgent if repacking else ScheduledAgent if scheduled else CompactAgent if compact else DissipativeAgent if dissipative else Agent)(expected_policy, paths, expected_dna)
    if payload['identity'] != agent.identity:
        raise ValueError('Checkpoint identity mismatch')
    step = integer(payload['last_step'], -1, 2**53-1)
    for s in sources:
        descriptor = payload['descriptors'][s]
        exact(descriptor, ('codec','value_path'))
        if type(descriptor['codec']) is not str or not descriptor['codec'] or len(descriptor['codec']) > 128:
            raise ValueError('Invalid codec')
        parts = descriptor['value_path']
        if type(parts) is not list or not 1 <= len(parts) <= 16 or any(type(x) is not str or len(x)>4096 for x in parts):
            raise ValueError('Invalid descriptor')
        integer(payload['last_refresh'][s], 0, max(0,step))
        number(payload['last_cost'][s], 0, expected_dna.max_calls)
        number(payload['errors'][s], 0, 1)
    number(payload['temperature'], 0, 1)
    restore_predictor(payload['predictor'],agent.model)
    rng = payload['rng']
    if type(rng) is not list or len(rng) != 3 or type(rng[0]) is not int or rng[0] != 3 or type(rng[1]) is not list or len(rng[1]) != 625 or rng[2] is not None:
        raise ValueError('Invalid RNG state')
    for x in rng[1][:-1]:integer(x,0,2**32-1)
    integer(rng[1][-1],0,624)
    agent.rng.setstate((3,tuple(rng[1]),None))
    for field in ('paths','descriptors','last_refresh','last_cost','errors','temperature','last_step'):
        # Detach nested state from caller-owned dictionaries.
        setattr(agent,field,json.loads(json.dumps(payload[field])))
    if dissipative:
        import re
        state=payload['retirement']
        exact(state,('stream','sequence','pending','accepted','pressure','retry_after','backoff') + (('retired_events','accepted_events','merges') if compact else ()))
        if type(state['stream']) is not str or not re.fullmatch('[0-9a-f]{32}',state['stream']):raise ValueError('Invalid retirement stream')
        seq=integer(state['sequence'],0,2**53-1)
        accepted=integer(state['accepted'],0,seq)
        integer(state['retry_after'],0,2**53-1);integer(state['backoff'],1,32)
        number(state['pressure'],0,1)
        pending=state['pending']
        if type(pending) is not list or len(pending)>expected_dna.retirement_capacity or len(pending)!=seq-accepted:
            raise ValueError('Invalid retirement conservation')
        for index,event in enumerate(pending,accepted+1):
            exact(event,('sequence','digest') + (('count','sealed') if compact else ()))
            if type(event['sequence']) is not int or event['sequence']!=index or type(event['digest']) is not str or not re.fullmatch('[0-9a-f]{64}',event['digest']):raise ValueError('Invalid retirement event')
        if compact:
            for index,event in enumerate(pending):
                integer(event['count'],1,2**53-1)
                if type(event['sealed']) is not bool or (index>0 and event['sealed']):raise ValueError('Invalid frozen batch')
            retired=integer(state['retired_events'],0,2**53-1)
            accepted_events=integer(state['accepted_events'],accepted,retired)
            merges=integer(state['merges'],0,retired)
            if retired != accepted_events+sum(e['count'] for e in pending) or retired != seq+merges:
                raise ValueError('Invalid compact conservation')
        agent.retirement=json.loads(json.dumps(state))
    if cells:
        state=payload['cells'];exact(state,('models','temperatures'))
        model_sources=sources[1:] if expected_dna.learning_scope=='source' else ()
        exact(state['models'],model_sources)
        for source in model_sources:restore_predictor(state['models'][source],agent.cell_models[source])
        temp_sources=sources if expected_dna.temperature_scope=='source' else ()
        exact(state['temperatures'],temp_sources)
        for source in temp_sources:agent.cell_temperatures[source]=number(state['temperatures'][source],0,1)
        if temp_sources and abs(agent.temperature-sum(agent.cell_temperatures.values())/len(temp_sources))>1e-12:raise ValueError('Inconsistent cell temperature aggregate')
    if scheduled:
        data=payload['emission'];exact(data,('state','predictor'))
        state=data['state'];exact(state,('last_attempt','refusal_ema','born'))
        last=integer(state['last_attempt'],0,max(0,step))
        number(state['refusal_ema'],0,1)
        pending=agent.retirement['pending']
        exact(state['born'],tuple(str(e['sequence']) for e in pending))
        births=[integer(state['born'][str(e['sequence'])],0,max(0,step)) for e in pending]
        if births!=sorted(births):raise ValueError('Invalid batch chronology')
        if agent.retirement['backoff']>expected_dna.reaction_horizon or agent.retirement['retry_after']>last+expected_dna.reaction_horizon:
            raise ValueError('Invalid scheduling horizon')
        restore_predictor(data['predictor'],agent.emission_model)
        agent.emission_state=json.loads(json.dumps(state))
    return agent


def save_checkpoint(agent, destination):
    """Atomically replace a checkpoint; caller serializes access between steps."""
    payload_raw = canonical(snapshot(agent))
    payload = json.loads(payload_raw)
    restore(payload,agent.dna,agent.policy)  # Validate before replacing any old state.
    receipt=getattr(agent,'_task_receipt',None)
    if receipt is None:
        digest=hashlib.sha256(payload_raw).hexdigest()
        prefix=b'{"payload":'+payload_raw
    else:
        from .receipt import FORMAT,validate_receipt
        validate_receipt(receipt,agent)
        # Reuse canonical payload bytes; all variable fields remain JSON encoded.
        prefix=(b'{"format":'+canonical(FORMAT)+b',"payload":'+payload_raw
                +b',"receipt":'+canonical(receipt))
        digest=hashlib.sha256(prefix+b'}').hexdigest()
    # The envelope keys are in the same sorted order as canonical(document).
    raw=prefix+b',"sha256":'+canonical(digest)+b'}'
    if len(raw)>MAX_BYTES:raise ValueError('Checkpoint too large')
    path = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.'+path.name+'.',delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
        temporary = None
        # Persist the rename where directory fsync is available (POSIX).
        if os.name == 'posix':
            fd = os.open(path.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def load_checkpoint(source, expected_dna, expected_policy):
    """Restore under caller-supplied identity/configuration, never file authority."""
    with Path(source).open('rb') as handle:raw=handle.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Checkpoint too large')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate checkpoint key')
            result[key]=value
        return result
    try:
        document=json.loads(raw,object_pairs_hook=unique)
        receipt=None
        if type(document) is dict and 'format' in document:
            from .receipt import FORMAT,validate_receipt
            exact(document,('format','payload','receipt','sha256'))
            if document['format']!=FORMAT:raise ValueError('Unknown task checkpoint format')
            unsigned={key:document[key] for key in ('format','payload','receipt')}
            digest=hashlib.sha256(canonical(unsigned)).hexdigest()
            receipt=document['receipt']
        else:
            exact(document,('payload','sha256'))
            digest=hashlib.sha256(canonical(document['payload'])).hexdigest()
        if type(document['sha256']) is not str or document['sha256']!=digest:
            raise ValueError('Checkpoint checksum mismatch')
        agent=restore(document['payload'],expected_dna,expected_policy)
        if 'format' in document:
            validate_receipt(receipt,agent)
            agent._task_receipt=receipt
        return agent
    except (TypeError,OverflowError,RecursionError,UnicodeError) as exc:
        raise ValueError('Invalid checkpoint encoding or structure') from exc
