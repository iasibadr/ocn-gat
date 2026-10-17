"""Check VR-3 saved accounting, correct refusals and trace snapshots."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
run = json.loads(Path(sys.argv[1]).read_text())
assert run['protocol_commit']=='994240c'
assert run['protocol_sha256']==hashlib.sha256((root/'PROTOCOL.md').read_bytes()).hexdigest()
assert set(run['results'])=={'silence_retablissement','signaux_incertains','indisponibilite'}
for episode, arms in run['results'].items():
    assert set(arms)=={'sticky','alert_classic','risk_classic','ocn_viability'}
    for policy, result in arms.items():
        rows = result['rows']
        assert result['exact']==len(rows)==sum(r['correct'] for r in rows)
        assert result['task_attempts']==sum(r['task_attempts'] for r in rows)
        assert result['task_failures']==sum(r['task_failures'] for r in rows)
        assert result['probes']==rows[-1]['probes']
        assert result['probe_failures']==rows[-1]['probe_failures']
        assert result['net_value']==round(sum(r['score'] for r in rows)-.05*result['probes'],6)
        assert run['calls'][episode+'/'+policy]==2
        for r in rows:
            expected_refusal=episode=='indisponibilite' and r['index'] in (3,4)
            if expected_refusal:
                assert r['response'] is None and 'Pinned version unavailable' in r['error']
            else:
                assert r['response']['values']=={'origin':'Taza','destination':'Fes'}
            for event in r['lease_events']:
                assert event['proof']['request']==r['index']
                assert event['document']==r['alert']
                if event['proof']['route'] is not None:
                    assert event['receipts'][0]['route']==event['proof']['route']
            if policy=='ocn_viability':
                assert set(r['route_state'])=={'A','B'}
    # The new rule is not promoted if it misses the preregistered criterion.
    assert arms['ocn_viability']['exact']==arms['risk_classic']['exact']
print('VR-3 accounting, refusals and route-state snapshots verified')
