"""Local Linux application shell for bounded OCN integer missions."""
import argparse
from contextlib import contextmanager
import json
import os
import tempfile
from pathlib import Path
import time
import uuid
from . import (RepackingAgent, RepackingDNA, CompactReservoir, DissipativeHabitat,
               DirectoryHabitat, TaskSpec, ToolSession, load_checkpoint, recover_task_receipt)


def configuration(habitat, paths, operation, model, *, validate_habitat=True):
    habitat = Path(habitat).resolve(strict=validate_habitat)
    if type(paths) is not dict or not paths or any(type(k) is not str or type(v) is not str for k,v in paths.items()):
        raise ValueError('Nonempty source-to-path mapping required')
    if type(model) is not str or not model.strip():
        raise ValueError('Local model identifier required')
    task = TaskSpec(operation, tuple(paths))
    dna = RepackingDNA(source_ids=task.sources, max_cache=len(paths), max_calls=10,
        require_schema_binding=True, scheduler='paced32', aggregation='eager', emission_phase='after')
    RepackingAgent('reactive', paths, dna)
    if validate_habitat:
        DirectoryHabitat(habitat, dna)
    return dict(format='ocn.local-application.v1', habitat=str(habitat), paths=paths,
                sources=list(task.sources), operation=operation, model=model)


def create(instance, habitat, paths, operation='sum', model='qwen3.5:9b'):
    config = configuration(habitat, paths, operation, model)
    root = Path(instance).resolve()
    h = Path(config['habitat'])
    if root == h or h in root.parents or root in h.parents:
        raise ValueError('Instance and habitat must be separate, non-nested directories')
    root.mkdir(parents=False, exist_ok=False)
    with (root/'instance.json').open('x') as f:
        json.dump(config, f, indent=2)
    write_lifecycle(root, 'active')
    return dict(instance=str(root), model=model, operation=operation, sources=config['sources'], lifecycle='active')


def load(instance):
    root = Path(instance).resolve(strict=True)
    config = json.loads((root/'instance.json').read_text())
    if type(config) is not dict or set(config) != {'format','habitat','paths','sources','operation','model'} or config['format'] != 'ocn.local-application.v1':
        raise ValueError('Invalid instance manifest')
    if type(config['sources']) is not list or type(config['paths']) is not dict or set(config['sources']) != set(config['paths']):
        raise ValueError('Invalid source order')
    paths = {s: config['paths'][s] for s in config['sources']}
    checked = configuration(config['habitat'], paths, config['operation'], config['model'], validate_habitat=False)
    if checked != config:
        raise ValueError('Noncanonical instance manifest')
    h = Path(config['habitat'])
    if root == h or h in root.parents or root in h.parents:
        raise ValueError('Instance must remain separate from habitat')
    dna = RepackingDNA(source_ids=tuple(config['sources']), max_cache=len(paths), max_calls=10,
        require_schema_binding=True, scheduler='paced32', aggregation='eager', emission_phase='after')
    return root, config, dna, TaskSpec(config['operation'],tuple(config['sources']))


@contextmanager
def locked(root):
    # Local trusted-host single-writer lock. This is not an OS sandbox.
    import fcntl
    with (root/'instance.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Instance is already executing') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def lifecycle(root):
    path = root/'lifecycle.json'
    if not path.exists():
        return 'uninitialized'  # Legacy or interrupted creation; never silently run.
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError('Duplicate lifecycle fields')
        return result
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {'format','state'}
        or value['format'] != 'ocn.lifecycle.v1' or value['state'] not in ('active','paused')):
        raise ValueError('Invalid lifecycle state')
    return value['state']


def write_lifecycle(root, state):
    if state not in ('active','paused'):
        raise ValueError('Invalid lifecycle state')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=root, prefix='.lifecycle-', delete=False) as f:
            temporary = Path(f.name)
            json.dump(dict(format='ocn.lifecycle.v1', state=state), f)
            f.flush(); os.fsync(f.fileno())
        os.replace(temporary, root/'lifecycle.json')
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()


def set_paused(instance, paused):
    if type(paused) is not bool: raise ValueError('Expected boolean pause state')
    root,config,dna,task = load(instance)
    with locked(root):
        previous = lifecycle(root)  # Malformed state is never silently overwritten.
        desired = 'paused' if paused else 'active'
        if previous != desired: write_lifecycle(root, desired)
        return dict(instance=str(root), lifecycle=desired, changed=previous != desired)


def status(instance):
    root,config,dna,task = load(instance)
    with locked(root):
        state = root/'state.json'
        agent = load_checkpoint(state,dna,'reactive') if state.exists() else RepackingAgent('reactive',config['paths'],dna)
        return dict(instance=str(root), model=config['model'], operation=task.operation,
                    identity=agent.identity, last_step=agent.last_step, persisted=state.exists(), lifecycle=lifecycle(root),
                    paths=agent.paths, retirement=agent.retirement)


def recover(instance, step, request_id):
    root,config,dna,task = load(instance)
    with locked(root):
        return recover_task_receipt(root/'state.json',dna,'reactive',request_id=request_id,step=step,task=task)


def run(instance, step, *, request_id=None, model=None, runner=None):
    root,config,dna,task = load(instance)
    selected_model = config['model'] if model is None else model
    if type(selected_model) is not str or not selected_model.strip():
        raise ValueError('Local model identifier required')
    request_id = uuid.uuid4().hex if request_id is None else request_id
    with locked(root):
        if lifecycle(root) != 'active':
            raise RuntimeError('Instance is paused or uninitialized; explicit resume required')
        model_info = None
        if runner is None:
            from .local_models import require_model
            model_info = require_model(selected_model)
            from .integrations.smolagents import run_session
            runner = run_session
        state = root/'state.json'
        agent = load_checkpoint(state,dna,'reactive') if state.exists() else RepackingAgent('reactive',config['paths'],dna)
        tools = DissipativeHabitat(config['habitat'],dna,CompactReservoir(root/'reservoir.sqlite',16))
        session = ToolSession(agent,tools,step,max_decisions=14,task=task,request_id=request_id,stage_metadata=True)
        trace = runner(session,time.monotonic()+90,model_id=selected_model)
        result = session.persist(state)
        model_trace = trace.get('model_trace',[])
        return dict(request_id=request_id, model=selected_model, model_digest=model_info['digest'] if model_info else None, result=result, error=trace.get('error'),
                    model_calls=len(model_trace),
                    input_tokens=sum((r.get('response') or {}).get('prompt_eval_count',0) for r in model_trace),
                    output_tokens=sum((r.get('response') or {}).get('eval_count',0) for r in model_trace))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('models')
    c=sub.add_parser('create');c.add_argument('instance');c.add_argument('--habitat',required=True)
    c.add_argument('--source',action='append',required=True);c.add_argument('--operation',choices=('sum','difference','minimum','maximum'),default='sum');c.add_argument('--model',default='qwen3.5:9b')
    r=sub.add_parser('run');r.add_argument('instance');r.add_argument('--step',type=int,required=True);r.add_argument('--request-id');r.add_argument('--model')
    s=sub.add_parser('status');s.add_argument('instance')
    for command in ('pause','resume'):
        control=sub.add_parser(command);control.add_argument('instance')
    g=sub.add_parser('recover');g.add_argument('instance');g.add_argument('--step',type=int,required=True);g.add_argument('--request-id',required=True)
    args=parser.parse_args()
    try:
        if args.command=='models':
            from .local_models import installed_models
            result=dict(provider='ollama_loopback',models=installed_models())
        elif args.command=='create':
            paths={}
            for item in args.source:
                if '=' not in item:raise ValueError('Source must be NAME=RELATIVE_PATH')
                name,path=item.split('=',1)
                if name in paths:raise ValueError('Duplicate source')
                paths[name]=path
            result=create(args.instance,args.habitat,paths,args.operation,args.model)
        elif args.command=='run':result=run(args.instance,args.step,request_id=args.request_id,model=args.model)
        elif args.command=='recover':result=recover(args.instance,args.step,args.request_id)
        elif args.command in ('pause','resume'):result=set_paused(args.instance,args.command=='pause')
        else:result=status(args.instance)
    except (ValueError,OSError,RuntimeError,ImportError) as exc:
        parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.command=='run' and (not result['result']['done'] or result['result']['refused']):return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
