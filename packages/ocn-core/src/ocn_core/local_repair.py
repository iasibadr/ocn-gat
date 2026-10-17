"""Bounded syntactic variations, selected by a host acceptance suite, not an LLM."""
import ast
from pathlib import Path
import json
from .agent_integration import Integration
from .candidate_evaluation import canonical,evaluate,validate_suite
from .candidate_adoption import pinned,check,adopt
from .bridge_repair import write

METHODS=frozenset(('strip','lstrip','rstrip','lower','upper','casefold'))


def variations(integration,limit=8):
    if type(integration) is not Integration:raise ValueError('Prepared integration required')
    integration.descriptor()
    if type(limit) is not int or not 1<=limit<=8:raise ValueError('Candidate limit must be 1..8')
    source=integration.source;tree=ast.parse(source.decode())
    calls=sorted((node for node in ast.walk(tree) if isinstance(node,ast.Call)
        and isinstance(node.func,ast.Attribute) and node.func.attr in METHODS
        and not node.args and not node.keywords),key=lambda n:(n.lineno,n.col_offset))
    if len(calls)>limit:raise ValueError('Candidate space exceeds explicit limit')
    # AST columns are UTF-8 byte offsets, not Unicode character offsets.
    offsets=[0]
    for line in source.splitlines(keepends=True):offsets.append(offsets[-1]+len(line))
    def span(node):return offsets[node.lineno-1]+node.col_offset,offsets[node.end_lineno-1]+node.end_col_offset
    result=[]
    for node in calls:
        start,end=span(node);left,right=span(node.func.value)
        altered=source[:start]+b'('+source[left:right]+b')'+source[end:]
        candidate=Integration(altered,integration.entrypoint);candidate.descriptor()
        result.append((dict(operation='remove_zero_argument_method',method=node.func.attr,
            line=node.lineno,column_utf8=node.col_offset),candidate))
    return result


def local_repair(instance,suite,output,*,limit=8,preserve_acceptance=False):
    from .gat import load,ISOLATED_FORMAT
    from .application import locked
    if type(limit) is not int or not 1<=limit<=8:raise ValueError('Candidate limit must be 1..8')
    if type(preserve_acceptance) is not bool:raise ValueError('Boolean acceptance preservation required')
    validate_suite(suite);suite=json.loads(canonical(suite))
    root,config=load(instance);output=Path(output).resolve()
    for protected in (root,Path(config['habitat']).resolve()):
        if output==protected or protected in output.parents or output in protected.parents:
            raise ValueError('Repair audit must be outside instance and habitat')
    with locked(root):
        root,config=load(root);check(root,config,config.get('integration',{}).get('sha256'))
        lineage=config.get('evolution',{})
        if preserve_acceptance and lineage:
            from .cumulative_adoption import read_retained,combine
            suite=combine(read_retained(root,lineage['suite_sha256']),suite)
        kind='response' if config['format']==ISOLATED_FORMAT else 'request'
        if any(set(c['expected'])!={kind} for c in suite['cases']):raise ValueError('Acceptance contract mismatch')
        current=pinned(root,config)
    output.mkdir(exist_ok=False)
    write(output/'started.json',dict(source=current.descriptor(),candidate_limit=limit,
        candidate_count=None,candidate_generation='after_failed_acceptance',model_calls=0,
        preserve_acceptance=preserve_acceptance,
        retained_suite_sha256=lineage.get('suite_sha256') if preserve_acceptance else None))
    try:
        baseline=evaluate(current,suite);write(output/'baseline.json',baseline)
        if baseline['accepted']:
            result=dict(status='already_accepted',adopted=False,tested_candidates=0,model_calls=0)
        else:
            candidates=variations(current,limit)
            write(output/'candidates.json',dict(candidate_count=len(candidates),candidate_limit=limit,model_calls=0))
            result=dict(status='no_passing_candidate',adopted=False,tested_candidates=0,model_calls=0)
            for index,(operation,candidate) in enumerate(candidates):
                folder=output/('candidate-'+str(index));folder.mkdir();candidate.write(folder)
                write(folder/'operation.json',operation)
                report=evaluate(candidate,suite);write(folder/'evaluation.json',report)
                result['tested_candidates']+=1
                if report['accepted']:
                    # Re-evaluate and switch under the instance lock with the original digest.
                    decision=adopt(root,candidate,suite,current.descriptor()['sha256'],
                                   expected_evolution=lineage if preserve_acceptance else None)
                    result.update(status='adopted' if decision['adopted'] else 'not_adopted',
                        adopted=decision['adopted'],selected_index=index,decision=decision)
                    break
        write(output/'result.json',result);return result
    except Exception as exc:
        write(output/'failure.json',dict(error_type=type(exc).__name__,status='failed_or_uncertain',inspect_instance_before_retry=True))
        raise
