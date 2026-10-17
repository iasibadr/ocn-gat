"""Verify PV-1 saved outcomes and accounting without another LLM run."""
import json
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text())
assert record['protocol_commit'] == 'da3f5c1'
assert record['protocol_sha256'] == __import__('hashlib').sha256(
    (Path(__file__).parent/'PROTOCOL.md').read_bytes()).hexdigest()
for episode, policies in record['results'].items():
    assert set(policies) == {'sticky', 'alert_classic', 'ocn_value'}
    for policy, result in policies.items():
        rows = result['rows']
        assert result['exact'] == sum(row['correct'] for row in rows)
        assert result['task_attempts'] == sum(row['task_attempts'] for row in rows)
        assert result['task_failures'] == sum(row['task_failures'] for row in rows)
        assert result['probes'] == rows[-1]['probe_attempts']
        assert result['probe_failures'] == rows[-1]['probe_failures']
        assert result['net_value'] == round(sum(row['score'] for row in rows)-.05*result['probes'], 6)
        assert record['calls'][episode+'/'+policy] == 2
        assert all(row['correct'] for row in rows)
        assert all(row['response']['values'] == {'origin':'Taza','destination':'Fes'}
                   for row in rows if row['response'] is not None)
        for row in rows:
            if row['stage'] == 'lose_A':
                assert row['response'] is None
                assert 'Pinned version unavailable' in row['error']
    assert policies['ocn_value']['net_value'] <= policies['alert_classic']['net_value']
print('PV-1 trace and accounting verified')
