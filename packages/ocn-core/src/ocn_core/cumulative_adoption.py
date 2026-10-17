"""Optional adoption that retains the acceptance cases of the current revision.

A finite regression guard, not a proof of general competence or monotonic reward.
The ordinary adoption API remains explicit replacement of its acceptance suite.
"""
import hashlib
import json
import os
import stat
from .candidate_adoption import adopt,check
from .candidate_evaluation import canonical,validate_suite
from .application import locked


def read_retained(root,digest):
    path=root/'acceptance-suites'/(digest+'.json')
    if path.parent.is_symlink():raise ValueError('Acceptance directory cannot be a symlink')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Regular acceptance suite required')
        raw=stream.read(65537)
    if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Retained acceptance integrity mismatch')
    from .gat import unique
    suite=json.loads(raw,object_pairs_hook=unique);validate_suite(suite);return suite


def combine(retained,incoming):
    """Union exact test cases; never drop a conflicting expectation or overflow."""
    validate_suite(retained);validate_suite(incoming)
    cases={}
    for suite in (retained,incoming):
        for case in suite['cases']:
            content={k:v for k,v in case.items() if k!='id'}
            digest=hashlib.sha256(canonical(content)).hexdigest()
            cases[digest]=dict(id='retained-'+digest,**content)
    merged=dict(format='gat.acceptance-suite.v1',cases=list(cases.values()))
    validate_suite(merged)  # Includes the existing 16-case / 64-KiB limits.
    return merged


def adopt_cumulative(instance,integration,suite,expected_current):
    """Revalidate retained + new cases and switch only through normal adoption.

    For a legacy revision lacking its exact retained suite, refuse instead of
    claiming preserved competence. Caller may supply a new suite on a fresh
    instance; no unknown historical tests are invented.
    """
    from .gat import load
    validate_suite(suite);incoming=json.loads(canonical(suite))
    root,_=load(instance)
    with locked(root):
        root,config=load(root);check(root,config,expected_current)
        lineage=config.get('evolution',{})
        previous=lineage.get('suite_sha256')
        retained=read_retained(root,previous) if previous else None
        merged=combine(retained,incoming) if retained else incoming
    # adopt rechecks expected current code under its own lock and evaluates both
    # versions against the exact merged cases. No cached success authorizes code.
    decision=adopt(root,integration,merged,expected_current,expected_evolution=lineage)
    return dict(**decision,retained_suite_sha256=previous,
                cumulative_cases=len(merged['cases']),
                preservation_scope='exact retained acceptance cases only')
