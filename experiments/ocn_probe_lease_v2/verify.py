"""Audit saved PV-2 accounting and one-request probe provenance."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
data = json.loads(Path(sys.argv[1]).read_text())
assert data['protocol_commit'] == '51645ae'
assert data['protocol_sha256'] == hashlib.sha256((root/'PROTOCOL.md').read_bytes()).hexdigest()
assert set(data['results']) == {'bascule','bruit_puis_rupture','miroir'}
for episode, arms in data['results'].items():
    assert set(arms) == {'sticky','alert_classic','risk_classic','ocn_lease'}
    for policy, summary in arms.items():
        rows = summary['rows']
        assert summary['exact'] == len(rows) == sum(r['correct'] for r in rows)
        assert summary['task_attempts'] == sum(r['task_attempts'] for r in rows)
        assert summary['task_failures'] == sum(r['task_failures'] for r in rows)
        assert summary['probes'] == rows[-1]['probes']
        assert summary['probe_failures'] == rows[-1]['probe_failures']
        assert summary['net_value'] == round(sum(r['score'] for r in rows)-.05*summary['probes'],6)
        assert data['calls'][episode+'/'+policy] == 2
        for r in rows:
            if r['stage'] == 'lose_A':
                assert r['response'] is None and 'Pinned version unavailable' in r['error']
            else:
                assert r['response']['values'] == {'origin':'Taza','destination':'Fes'}
            for event in r['lease_events']:
                proof = event['proof']
                assert proof['request'] == r['index']
                assert proof['document'] == event['document'] == r['alert']
                assert proof['sha256'] in {hashlib.sha256(t.encode()).hexdigest()
                                           for t in ('Shipment S has origin Taza.\n',
                                                     'Shipment S has destination Fes.\n')}
                if proof['route'] is not None:
                    assert event['receipts'][0]['route'] == proof['route']
            if r['watch']['action'] == 'skip':
                assert not r['lease_events']
        if policy == 'sticky':
            assert summary['probes'] == 0
    assert arms['ocn_lease']['exact'] == arms['risk_classic']['exact']
print('PV-2 corrected trace, value accounting and lease provenance verified')
