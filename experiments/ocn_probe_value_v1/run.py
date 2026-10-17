"""PV-1: compare when to probe, with the same evidence worker and source rights."""
import argparse
import hashlib
import json
import random
import tempfile
from pathlib import Path

from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_routes import RouteAdapter
from ocn_core.evidence_agent import EvidenceAgent
from ocn_core.extraction_organ import ExtractionOrgan
from ocn_core.local_evidence import extract
from ocn_core.local_models import require_model

from sys import path as import_path
import_path.insert(0, str(Path(__file__).resolve().parents[1]/'ocn_coupled_documents'))
from run import CoupledRoutes, FIELDS, QUESTION, TEXTS

HERE = Path(__file__).resolve().parent
STAGES = {
    'perturbations': ('initial', 'drop_A', 'alert_A', 'move_A_mirror',
                      'change_B', 'alert_B', 'lose_A', 'restore_A', 'alert_A'),
    'bruit': ('initial', *('alert_A',)*6, 'drop_A',
              'quiet', 'quiet', 'quiet', 'restore_A'),
}


class AlertClassic(RouteAdapter):
    def __init__(self, routes):
        super().__init__(routes, policy='sticky')
        self.names = tuple(routes)
        self.probe_attempts = self.probe_failures = 0
        self.probe_events = []

    def observe(self, changed):
        if changed is None:
            return dict(action='skip', reason='no_alert')
        first = self.preferred.get(changed, self.names[0])
        attempts = []
        for name in (first, *[n for n in self.names if n != first]):
            self.probe_attempts += 1
            try:
                doc = self.routes[name].read(changed)
                if doc.sha256 != self.pinned[changed]:
                    raise ValueError('Unpinned source')
                good = True
            except (OSError, ValueError):
                good = False
                self.probe_failures += 1
            attempts.append(dict(route=name, good=good))
            if good:
                self.preferred[changed] = name
                break
        event = dict(action='probe', document=changed, attempts=attempts)
        self.probe_events.append(event)
        return event


class ValueRoutes(CoupledRoutes):
    def __init__(self, routes):
        super().__init__(routes)
        self.rng = random.Random(1)
        self.alerts = {doc: 0 for doc in self.pinned}
        self.bad = {doc: 0 for doc in self.pinned}
        self.last_success = {doc: self.names[0] for doc in self.pinned}
        self.probe_events = []

    def observe(self, changed):
        if changed is None:
            return dict(action='skip', reason='no_alert')
        first = self.last_success[changed]
        cell = self.cell[changed][first]
        historical = (1+self.bad[changed])/(2+self.alerts[changed])
        risk = .8*historical+.2*cell['x']
        predicted_gain = .5*risk
        predicted_probe_cost = .05*(1+risk)  # second read only if first fails
        before_attempts = self.probe_attempts
        if predicted_gain > predicted_probe_cost:
            self.last_probes = {}
            for name in (first, *[n for n in self.names if n != first]):
                self.probe_attempts += 1
                try:
                    doc = self.routes[name].read(changed)
                    if doc.sha256 != self.pinned[changed]:
                        raise ValueError('Unpinned source')
                    good = True
                except (OSError, ValueError):
                    good = False
                    self.probe_failures += 1
                self.last_probes[name] = good
                self._feedback(changed, name, good)
                if good:
                    self.last_success[changed] = name
                    break
            self.alerts[changed] += 1
            self.bad[changed] += int(not self.last_probes[first])
            action = 'probe'
        else:
            self.last_probes = {}
            action = 'skip'
        event = dict(action=action, document=changed, first=first,
                     risk=risk, expected_gain=predicted_gain,
                     probe_cost=predicted_probe_cost,
                     attempts=self.probe_attempts-before_attempts,
                     observations=dict(self.last_probes))
        self.probe_events.append(event)
        return event

    def read(self, document_id, *, discovery_bytes=None):
        before = len(self.cycles)
        result = super().read(document_id, discovery_bytes=discovery_bytes)
        if len(self.cycles) > before:
            receipts = self.cycles[-1]['receipts']
            for receipt in receipts:
                if receipt['status'] == 'value':
                    self.last_success[document_id] = receipt['route']
                    break
        return result


def change(base, stage):
    if stage == 'drop_A':
        (base/'primary/A.txt').unlink()
        return 'A'
    if stage == 'move_A_mirror':
        archive = base/'mirror/archive'
        archive.mkdir()
        (base/'mirror/A.txt').rename(archive/'moved.txt')
        return 'A'
    if stage == 'change_B':
        (base/'primary/B.txt').write_text('Shipment S has destination Rabat.\n')
        return 'B'
    if stage == 'lose_A':
        (base/'mirror/archive/moved.txt').write_text('Shipment S has origin Meknes.\n')
        return 'A'
    if stage == 'restore_A':
        target = base/'mirror/archive/moved.txt'
        if not target.exists():
            target = base/'primary/A.txt'
        target.write_text(TEXTS['A'])
        return 'A'
    if stage == 'alert_A':
        return 'A'
    if stage == 'alert_B':
        return 'B'
    return None


def episode(episode_name, policy, worker, revision):
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        routes = {}
        for name in ('primary', 'mirror'):
            root = base/name
            root.mkdir()
            adapter = DocumentAdapter(root, base/(name+'.json'))
            for ident, content in TEXTS.items():
                (root/(ident+'.txt')).write_text(content)
                adapter.bind(ident, ident+'.txt')
            routes[name] = adapter
        controller = (ValueRoutes(routes) if policy == 'ocn_value' else
                      AlertClassic(routes) if policy == 'alert_classic' else
                      RouteAdapter(routes, policy='sticky'))
        organ = ExtractionOrgan(worker, lambda: revision, max_cells=2,
                                entries_per_cell=4, max_reuses=16)
        agent = EvidenceAgent(controller, organ, extract_many=organ.extract_many)
        for index, stage in enumerate(STAGES[episode_name]):
            alert = change(base, stage)
            watch = controller.observe(alert) if policy != 'sticky' else dict(action='skip')
            before = (controller.attempts, controller.failures)
            try:
                response = agent.answer(QUESTION, FIELDS, ('A', 'B'))
                error = None
            except (ValueError, OSError) as exc:
                response = None
                error = type(exc).__name__+': '+str(exc)
            refusal_expected = stage == 'lose_A'
            valid_refusal = response is None and error is not None and \
                'Pinned version unavailable on all authorized routes' in error
            correct = valid_refusal if refusal_expected else (
                response is not None and not response['abstain'] and
                response['values'] == {'origin': 'Taza', 'destination': 'Fes'})
            task_attempts = controller.attempts-before[0]
            score = (1. if refusal_expected and valid_refusal else 1. if correct and task_attempts <= 4
                     else .5 if correct else 0.)
            if policy == 'ocn_value':
                controller.regulate(correct)
            rows.append(dict(index=index, stage=stage, alert=alert, watch=watch,
                             correct=correct, score=score, task_attempts=task_attempts,
                             task_failures=controller.failures-before[1],
                             probe_attempts=getattr(controller, 'probe_attempts', 0),
                             probe_failures=getattr(controller, 'probe_failures', 0),
                             response=None if response is None else dict(
                                 values=response['values'], paths=response['source_paths'],
                                 abstain=response['abstain']), error=error,
                             memory=organ.stats(),
                             last_decision=controller.cycles[-1] if policy == 'ocn_value' else None,
                             temperature=controller.temperature if policy == 'ocn_value' else None))
    probes = rows[-1]['probe_attempts']
    return dict(rows=rows, exact=sum(r['correct'] for r in rows),
                timely=sum(r['correct'] and r['task_attempts'] <= 4 for r in rows),
                task_attempts=sum(r['task_attempts'] for r in rows),
                task_failures=sum(r['task_failures'] for r in rows),
                probes=probes, probe_failures=rows[-1]['probe_failures'],
                net_value=round(sum(r['score'] for r in rows)-.05*probes, 6))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    model = require_model('qwen3.5:9b')
    results = {}
    calls = {}
    for episode_name in STAGES:
        results[episode_name] = {}
        for policy in ('sticky', 'alert_classic', 'ocn_value'):
            counter = [0]
            def worker(*params):
                counter[0] += 1
                return extract(*params)
            results[episode_name][policy] = episode(episode_name, policy, worker, model['digest'])
            calls[episode_name+'/'+policy] = counter[0]
    summary = dict(protocol_commit='da3f5c1',
                   protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
                   code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   model=model, calls=calls, results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({e: {p: {k:v for k,v in r.items() if k != 'rows'}
                          for p,r in policies.items()} for e,policies in results.items()}))


if __name__ == '__main__':
    main()
