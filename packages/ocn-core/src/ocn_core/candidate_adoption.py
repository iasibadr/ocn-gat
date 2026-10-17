"""Finite-suite adoption of isolated bridges; single atomic manifest switch."""
import json
import os
from pathlib import Path
import tempfile
from .agent_integration import Integration, PinnedSynthesizer, validate_descriptor, read_source
from .candidate_evaluation import evaluate, validate_suite, canonical
from .model_budget import sync_directory


def validate_evolution(value):
    if (type(value) is not dict or set(value)!={'revision','previous','suite_sha256'}
        or type(value['revision']) is not int or value['revision']<1):raise ValueError('Invalid evolution state')
    validate_descriptor(value['previous'])
    import re
    if type(value['suite_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',value['suite_sha256']) is None:
        raise ValueError('Invalid acceptance suite digest')


def pinned(root,config,descriptor=None):
    current=descriptor is None
    descriptor=config['integration'] if current else descriptor
    value=PinnedSynthesizer(root,descriptor,config['model'],revisioned=not current or 'evolution' in config)
    return Integration(value.source,value.entrypoint)


def check(root,config,expected):
    from .gat import ISOLATED_FORMAT,BROKERED_FORMAT
    from .application import lifecycle
    if config['format'] not in (ISOLATED_FORMAT,BROKERED_FORMAT):raise ValueError('Adoption requires isolated execution')
    if lifecycle(root) not in ('active','paused'):raise RuntimeError('Incomplete instance')
    if config['integration']['sha256']!=expected:raise ValueError('Current code conflict')


def store(root,integration):
    directory=root/'revisions';directory.mkdir(exist_ok=True)
    if directory.is_symlink():raise ValueError('Revision directory cannot be a symlink')
    path=directory/(integration.descriptor()['sha256']+'.py')
    try:
        with path.open('xb') as handle:
            handle.write(integration.source);handle.flush();os.fsync(handle.fileno())
    except FileExistsError:
        if read_source(path)!=integration.source:raise ValueError('Stored revision content mismatch')
    sync_directory(directory);sync_directory(root)


def store_acceptance(root,suite):
    """Persist the exact accepted suite; evidence for later cumulative adoption."""
    import hashlib
    raw=canonical(suite);digest=hashlib.sha256(raw).hexdigest()
    directory=root/'acceptance-suites';directory.mkdir(exist_ok=True)
    if directory.is_symlink():raise ValueError('Acceptance directory cannot be a symlink')
    path=directory/(digest+'.json')
    try:
        with path.open('xb') as handle:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
    except FileExistsError:
        if path.is_symlink() or path.read_bytes()!=raw:raise ValueError('Stored acceptance content mismatch')
    sync_directory(directory);sync_directory(root)
    return digest


def switch(root,config):
    from .gat import validate
    validate(config)
    fd,path=tempfile.mkstemp(prefix='.manifest-',dir=root)
    try:
        with os.fdopen(fd,'w') as handle:
            json.dump(config,handle,ensure_ascii=False,indent=2);handle.flush();os.fsync(handle.fileno())
        os.replace(path,root/'instance.json');sync_directory(root)
    finally:
        if os.path.exists(path):os.unlink(path)


def adopt(instance,integration,suite,expected_current,*,expected_evolution=None):
    from .gat import load,ISOLATED_FORMAT
    from .application import locked
    if type(integration) is not Integration:raise ValueError('Prepared integration required')
    integration.descriptor();validate_suite(suite)
    if expected_evolution is not None:
        if type(expected_evolution) is not dict:raise ValueError('Expected evolution snapshot must be a mapping')
        expected_evolution=json.loads(canonical(expected_evolution))
    suite=json.loads(canonical(suite))
    root,config=load(instance)
    with locked(root):
        # Reload under lock: do not use a manifest read before another adoption.
        root,config=load(root);check(root,config,expected_current)
        if expected_evolution is not None and config.get('evolution',{})!=expected_evolution:
            raise ValueError('Acceptance lineage changed during preparation')
        expected_kind='response' if config['format']==ISOLATED_FORMAT else 'request'
        if any(set(c['expected'])!={expected_kind} for c in suite['cases']):
            raise ValueError('Acceptance contract does not match instance execution mode')
        current=pinned(root,config)
        baseline=evaluate(current,suite)
        candidate=evaluate(integration,suite)
        report=dict(adopted=False,baseline=baseline,candidate=candidate)
        if not candidate['accepted'] or baseline['accepted']:
            return dict(report,reason='candidate_failed' if not candidate['accepted'] else 'no_demonstrated_improvement')
        store_acceptance(root,suite)
        store(root,current);store(root,integration)
        previous=config['integration']
        config=dict(config,integration=integration.descriptor(),evolution=dict(
            revision=config.get('evolution',{}).get('revision',0)+1,previous=previous,
            suite_sha256=candidate['suite_sha256']))
        switch(root,config)
        return dict(report,adopted=True,revision=config['evolution']['revision'],reason='candidate_passed_baseline_failed')


def rollback(instance,expected_current):
    from .gat import load
    from .application import locked
    root,config=load(instance)
    with locked(root):
        root,config=load(root);check(root,config,expected_current)
        if 'evolution' not in config:raise ValueError('No previous revision')
        previous=config['evolution']['previous']
        pinned(root,config,previous)  # Verify old bytes before switching.
        evolution=dict(config['evolution'],revision=config['evolution']['revision']+1,previous=config['integration'])
        config=dict(config,integration=previous,evolution=evolution)
        switch(root,config)
        return dict(rolled_back=True,revision=evolution['revision'],integration=previous)
