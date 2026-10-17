"""Inspect the completed CD-1 trace without rerunning model inference."""
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
arms = data['results']
assert set(arms) == {'classical', 'ocn'}
for name, rows in arms.items():
    assert len(rows) == 6
    assert all(r['correct'] for r in rows)
    assert [r['stage'] for r in rows] == [
        'initial', 'primary_A_missing', 'mirror_A_moved',
        'primary_B_changed', 'A_unavailable', 'A_restored']
    assert rows[4]['result'] is None
    assert 'Pinned version unavailable on all authorized routes' in rows[4]['error']
    assert all(r['result']['values'] == {'origin': 'Taza', 'destination': 'Fes'}
               for r in rows if r['result'] is not None)
    assert rows[-1]['memory']['batches'] == 5
    assert data['calls'][name] == 2
ocn = arms['ocn']
assert ocn[-1]['probe_attempts'] == 10
assert ocn[-1]['total_attempts'] == sum(r['task_attempts'] for r in ocn)+10
assert ocn[-1]['total_failures'] == sum(r['task_failures'] for r in ocn)+ocn[-1]['probe_failures']
assert ocn[1]['probes'] == {'primary': False, 'mirror': True}
assert ocn[4]['probes'] == {'primary': False, 'mirror': False}
assert ocn[5]['probes'] == {'primary': False, 'mirror': True}
assert len({r['temperature'] for r in ocn}) == 6
assert all(.1 <= r['temperature'] <= .5 for r in ocn)
assert all(set(d['probabilities']) == {'primary', 'mirror'} and
           abs(sum(d['probabilities'].values())-1) < 1e-12
           for r in ocn for d in r['recent_decisions'])
print('CD-1 trace verified: 6/6 each; OCN probes and feedback counted')
