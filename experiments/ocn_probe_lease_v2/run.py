"""PV-2: a fresh, one-request probe receipt constrains route selection."""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_routes import RouteAdapter
from ocn_core.evidence_agent import EvidenceAgent
from ocn_core.extraction_organ import ExtractionOrgan
from ocn_core.local_evidence import extract
from ocn_core.local_models import require_model

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.ocn_probe_value_v1.run import AlertClassic, ValueRoutes, FIELDS, QUESTION, TEXTS

HERE = Path(__file__).resolve().parent
STAGES = {
    'bascule': ('initial', 'change_B', 'alert_B', 'restore_B',
                'drop_A', 'alert_A', 'restore_A', 'change_B', 'restore_B'),
    'bruit_puis_rupture': ('initial', *('alert_A',)*5, 'drop_A', 'quiet', 'quiet',
                          'restore_A', 'alert_A', 'alert_A', 'drop_A', 'restore_A'),
    'miroir': ('initial', 'move_A_mirror', 'drop_A', 'alert_A', 'lose_A',
               'restore_A_mirror', 'change_B', 'restore_B'),
}


class Lease:
    """Mixin: a checked probe guides only the immediately following request."""
    def begin_request(self, index):
        self.request_index = index
        self.lease = {}
        self.lease_events = []

    def install_lease(self, changed, observations):
        if changed is None or not observations:
            return
        good = next((name for name, valid in observations.items() if valid), None)
        bad = [name for name, valid in observations.items() if not valid]
        self.lease[changed] = dict(document=changed, route=good,
                                   invalid=bad, sha256=self.pinned[changed],
                                   request=self.request_index)

    def end_request(self):
        self.lease = {}

    def _leased_read(self, doc, discovery_bytes=None):
        proof = self.lease.get(doc)
        if proof is None:
            return None
        if proof['request'] != self.request_index or proof['sha256'] != self.pinned[doc]:
            raise ValueError('Expired or altered probe receipt')
        route = proof['route']
        if route is None:
            allowed = [n for n in self.names if n not in proof['invalid']]
            if not allowed:
                # A refusal still requires an actual fresh source read.
                allowed = list(self.names)
            route = allowed[0]
        order = (route, *[n for n in self.names if n != route])
        original_routes, original_policy = self.routes, self.policy
        self.routes = {n: original_routes[n] for n in order}
        self.policy = 'fixed'
        before = self.attempts
        try:
            return RouteAdapter.read(self, doc, discovery_bytes=discovery_bytes)
        finally:
            self.routes, self.policy = original_routes, original_policy
            receipts = self.events[-(self.attempts-before):] if self.attempts>before else []
            if original_policy == 'sticky':
                for event in receipts:
                    if event['status'] == 'value':
                        self.preferred[doc] = event['route']
                        break
            if hasattr(self, 'cell'):
                for event in receipts:
                    self._feedback(doc, event['route'], event['status'] == 'value')
                    if event['status'] == 'value':
                        self.last_success[doc] = event['route']
            self.lease_events.append(dict(document=doc, proof=proof,
                receipts=[dict(route=e['route'], status=e['status']) for e in receipts]))


class LeasedAlert(Lease, AlertClassic):
    def observe(self, changed):
        event = super().observe(changed)
        observations = {a['route']: a['good'] for a in event.get('attempts', [])}
        self.install_lease(changed, observations)
        return event

    def read(self, document_id, *, discovery_bytes=None):
        if document_id in self.lease:
            return self._leased_read(document_id, discovery_bytes)
        return RouteAdapter.read(self, document_id, discovery_bytes=discovery_bytes)


class LeasedValue(Lease, ValueRoutes):
    def observe(self, changed):
        event = super().observe(changed)
        self.install_lease(changed, event.get('observations', {}))
        return event

    def read(self, document_id, *, discovery_bytes=None):
        if document_id in self.lease:
            return self._leased_read(document_id, discovery_bytes)
        return ValueRoutes.read(self, document_id, discovery_bytes=discovery_bytes)


class LeasedRiskClassic(LeasedValue):
    def __init__(self, routes):
        super().__init__(routes)
        self.policy = 'sticky'

    def read(self, document_id, *, discovery_bytes=None):
        if document_id in self.lease:
            return self._leased_read(document_id, discovery_bytes)
        before = self.attempts
        try:
            return RouteAdapter.read(self, document_id, discovery_bytes=discovery_bytes)
        finally:
            for event in self.events[-(self.attempts-before):] if self.attempts>before else []:
                self._feedback(document_id, event['route'], event['status'] == 'value')
                if event['status'] == 'value':
                    self.last_success[document_id] = event['route']


def mutate(base, stage):
    if stage == 'drop_A':
        (base/'primary/A.txt').unlink()
        return 'A'
    if stage == 'restore_A':
        (base/'primary/A.txt').write_text(TEXTS['A'])
        return 'A'
    if stage == 'move_A_mirror':
        archive = base/'mirror/archive'
        archive.mkdir()
        (base/'mirror/A.txt').rename(archive/'moved.txt')
        return 'A'
    if stage == 'lose_A':
        (base/'mirror/archive/moved.txt').write_text('Shipment S has origin Meknes.\n')
        return 'A'
    if stage == 'restore_A_mirror':
        (base/'mirror/archive/moved.txt').write_text(TEXTS['A'])
        return 'A'
    if stage == 'change_B':
        (base/'primary/B.txt').write_text('Shipment S has destination Rabat.\n')
        return 'B'
    if stage == 'restore_B':
        (base/'primary/B.txt').write_text(TEXTS['B'])
        return 'B'
    if stage == 'alert_A':
        return 'A'
    if stage == 'alert_B':
        return 'B'
    return None


def run_episode(name, policy, worker, revision):
    rows = []
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        routes = {}
        for route in ('primary', 'mirror'):
            root = base/route
            root.mkdir()
            adapter = DocumentAdapter(root, base/(route+'.json'))
            for doc, content in TEXTS.items():
                (root/(doc+'.txt')).write_text(content)
                adapter.bind(doc, doc+'.txt')
            routes[route] = adapter
        controller = (RouteAdapter(routes, policy='sticky') if policy == 'sticky' else
                      LeasedAlert(routes) if policy == 'alert_classic' else
                      LeasedRiskClassic(routes) if policy == 'risk_classic' else
                      LeasedValue(routes))
        organ = ExtractionOrgan(worker, lambda: revision, max_cells=2,
                                entries_per_cell=4, max_reuses=16)
        agent = EvidenceAgent(controller, organ, extract_many=organ.extract_many)
        for index, stage in enumerate(STAGES[name]):
            alert = mutate(base, stage)
            if policy != 'sticky':
                controller.begin_request(index)
                watch = controller.observe(alert)
            else:
                watch = dict(action='skip')
            attempts_before, failures_before = controller.attempts, controller.failures
            try:
                answer = agent.answer(QUESTION, FIELDS, ('A', 'B'))
                error = None
            except (ValueError, OSError) as exc:
                answer = None
                error = type(exc).__name__+': '+str(exc)
            expected_refusal = stage == 'lose_A'
            valid_refusal = answer is None and error is not None and \
                'Pinned version unavailable on all authorized routes' in error
            correct = valid_refusal if expected_refusal else (
                answer is not None and not answer['abstain'] and
                answer['values'] == {'origin':'Taza','destination':'Fes'})
            task_attempts = controller.attempts-attempts_before
            score = (1. if expected_refusal and valid_refusal else
                     1. if correct and task_attempts<=4 else .5 if correct else 0.)
            if policy != 'sticky':
                leases = list(controller.lease_events)
                controller.end_request()
            else:
                leases = []
            if policy in ('risk_classic', 'ocn_lease'):
                controller.regulate(correct)
            rows.append(dict(index=index, stage=stage, alert=alert, watch=watch,
                lease_events=leases, correct=correct, score=score,
                task_attempts=task_attempts,
                task_failures=controller.failures-failures_before,
                probes=getattr(controller,'probe_attempts',0),
                probe_failures=getattr(controller,'probe_failures',0),
                response=None if answer is None else dict(values=answer['values'],
                    paths=answer['source_paths'], abstain=answer['abstain']), error=error,
                memory=organ.stats(), temperature=getattr(controller,'temperature',None)))
    probes = rows[-1]['probes']
    return dict(rows=rows, exact=sum(r['correct'] for r in rows),
                timely=sum(r['correct'] and r['task_attempts']<=4 for r in rows),
                task_attempts=sum(r['task_attempts'] for r in rows),
                task_failures=sum(r['task_failures'] for r in rows),
                probes=probes, probe_failures=rows[-1]['probe_failures'],
                net_value=round(sum(r['score'] for r in rows)-.05*probes,6))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    model = require_model('qwen3.5:9b')
    results, calls = {}, {}
    for episode in STAGES:
        results[episode] = {}
        for policy in ('sticky','alert_classic','risk_classic','ocn_lease'):
            counter = [0]
            def worker(*args):
                counter[0] += 1
                return extract(*args)
            results[episode][policy] = run_episode(episode,policy,worker,model['digest'])
            calls[episode+'/'+policy] = counter[0]
    output = dict(protocol_commit='51645ae',
                  protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
                  code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  model=model, calls=calls, results=results)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({e:{p:{k:v for k,v in r.items() if k!='rows'}
                         for p,r in arms.items()} for e,arms in results.items()}))


if __name__ == '__main__':
    main()
