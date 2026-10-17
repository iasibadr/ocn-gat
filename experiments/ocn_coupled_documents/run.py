"""CD-1: bounded causal document loop with identical evidence worker on both arms."""
import argparse
import hashlib
import json
import math
import random
import tempfile
from pathlib import Path

from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_routes import RouteAdapter
from ocn_core.evidence_agent import EvidenceAgent
from ocn_core.extraction_organ import ExtractionOrgan
from ocn_core.local_evidence import extract
from ocn_core.local_models import require_model

HERE = Path(__file__).resolve().parent
TEXTS = {'A': 'Shipment S has origin Taza.\n', 'B': 'Shipment S has destination Fes.\n'}
FIELDS = {'origin': 'Copy origin city exactly.', 'destination': 'Copy destination city exactly.'}
QUESTION = 'What are the origin and destination of shipment S?'
STAGES = ('initial', 'primary_A_missing', 'mirror_A_moved',
          'primary_B_changed', 'A_unavailable', 'A_restored')


def hamilton(a, b):
    x, y, z, w = a
    u, v, r, s = b
    return (x*u-y*v-z*r-w*s, x*v+y*u+z*s-w*r,
            x*r-y*s+z*u+w*v, x*s+y*r-z*v+w*u)


class CoupledRoutes(RouteAdapter):
    """Experimental planner; ordinary adapters still enforce pinned versions."""
    def __init__(self, routes):
        super().__init__(routes, policy='fixed')
        self.names = tuple(routes)
        self.rng = random.Random(17)
        self.cell = {doc: {name: dict(x=.5, t=.5, q=.5, uncertainty=1.)
                           for name in self.names} for doc in self.pinned}
        self.temperature = .2
        self.probe_attempts = 0
        self.probe_failures = 0
        self.cycles = []
        self.last_probes = {}

    def observe(self, changed):
        """Bounded read-only between-request probes, not oracle availability."""
        self.last_probes = {}
        if changed is None:
            return
        for name in self.names:
            self.probe_attempts += 1
            try:
                doc = self.routes[name].read(changed)
                if doc.sha256 != self.pinned[changed]:
                    raise ValueError('Unpinned version')
                good = True
            except (OSError, ValueError):
                good = False
                self.probe_failures += 1
            self.last_probes[name] = good
            self._feedback(changed, name, good)

    def _feedback(self, doc, name, good):
        c = self.cell[doc][name]
        c['x'] = .25*c['x'] + .75*(0. if good else 1.)
        c['t'] = min(1., .5*c['t'] + .25)
        c['q'] = .4*c['q'] + .6*(0. if good else 1.)
        c['uncertainty'] = max(.05, .5*c['uncertainty'])

    def read(self, document_id, *, discovery_bytes=None):
        if document_id not in self.pinned:
            raise ValueError('Unknown document identifier')
        cells = self.cell[document_id]
        # Hamilton relation is a candidate interaction, not a claim of optimality.
        vectors = {name: (c['x'], c['t'], c['q'], c['uncertainty'])
                   for name, c in cells.items()}
        reference = tuple(sum(v[i] for v in vectors.values())/len(vectors)
                          for i in range(4))
        costs = {}
        for name, v in vectors.items():
            relative = hamilton(v, (reference[0], -reference[1],
                                     -reference[2], -reference[3]))
            costs[name] = max(0., .5*v[0]+.2*v[1]+.2*v[2]+.1*v[3]
                              +.05*sum(abs(a) for a in relative[1:]))
        logits = {n: math.exp(-(costs[n]-min(costs.values()))/self.temperature)
                  for n in self.names}
        total = sum(logits.values())
        probabilities = {n: logits[n]/total for n in self.names}
        threshold = self.rng.random()
        first = self.names[-1]
        for name in self.names:
            threshold -= probabilities[name]
            if threshold <= 0:
                first = name
                break
        old_routes = self.routes
        old_events = len(self.events)
        before_attempts = self.attempts
        self.routes = {n: old_routes[n] for n in (first, *[n for n in self.names if n != first])}
        try:
            return super().read(document_id, discovery_bytes=discovery_bytes)
        finally:
            self.routes = old_routes
            receipts = self.events[old_events:]
            # RouteAdapter's bounded event log can wrap; use the attempt delta.
            if self.attempts-before_attempts > len(receipts):
                receipts = self.events[-(self.attempts-before_attempts):]
            for event in receipts:
                self._feedback(document_id, event['route'], event['status'] == 'value')
            self.cycles.append(dict(document=document_id, cells=vectors,
                                    hamilton_reference=reference, costs=costs,
                                    temperature=self.temperature,
                                    probabilities=probabilities, selected=first,
                                    receipts=[dict(route=e['route'], status=e['status'])
                                              for e in receipts]))

    def regulate(self, success):
        self.temperature = max(.1, min(.5, .8*self.temperature + .2*(.1 if success else .5)))


def mutate(base, stage):
    if stage == 'primary_A_missing':
        (base/'primary/A.txt').unlink()
        return 'A'
    if stage == 'mirror_A_moved':
        (base/'mirror/archive').mkdir()
        (base/'mirror/A.txt').rename(base/'mirror/archive/moved.txt')
        return 'A'
    if stage == 'primary_B_changed':
        (base/'primary/B.txt').write_text('Shipment S has destination Rabat.\n')
        return 'B'
    if stage == 'A_unavailable':
        (base/'mirror/archive/moved.txt').write_text('Shipment S has origin Meknes.\n')
        return 'A'
    if stage == 'A_restored':
        (base/'mirror/archive/moved.txt').write_text(TEXTS['A'])
        return 'A'
    return None


def scenario(kind, worker, revision):
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        routes = {}
        for name in ('primary', 'mirror'):
            root = base/name
            root.mkdir()
            adapter = DocumentAdapter(root, base/(name+'.json'))
            for ident, content in TEXTS.items():
                (root/(ident+'.txt')).write_text(content)
                adapter.bind(ident, ident+'.txt')
            routes[name] = adapter
        controller = CoupledRoutes(routes) if kind == 'ocn' else RouteAdapter(routes, policy='sticky')
        organ = ExtractionOrgan(worker, lambda: revision, max_cells=2,
                                entries_per_cell=4, max_reuses=8)
        agent = EvidenceAgent(controller, organ, extract_many=organ.extract_many)
        for stage in STAGES:
            changed = mutate(base, stage)
            if kind == 'ocn':
                controller.observe(changed)
            before = (controller.attempts, controller.failures)
            try:
                result = agent.answer(QUESTION, FIELDS, ('A', 'B'))
                error = None
            except (ValueError, OSError) as exc:
                result = None
                error = type(exc).__name__+': '+str(exc)
            correct = (result is None and error is not None and
                       'Pinned version unavailable on all authorized routes' in error) if stage == 'A_unavailable' else (
                result is not None and not result['abstain'] and
                result['values'] == {'origin': 'Taza', 'destination': 'Fes'})
            if kind == 'ocn':
                controller.regulate(correct)
            rows.append(dict(stage=stage, changed=changed, correct=correct,
                             result=None if result is None else dict(values=result['values'],
                                 abstain=result['abstain'], paths=result['source_paths']),
                             error=error, task_attempts=controller.attempts-before[0],
                             task_failures=controller.failures-before[1],
                             probe_attempts=controller.probe_attempts if kind == 'ocn' else 0,
                             probe_failures=controller.probe_failures if kind == 'ocn' else 0,
                             total_attempts=controller.attempts+(controller.probe_attempts if kind == 'ocn' else 0),
                             total_failures=controller.failures+(controller.probe_failures if kind == 'ocn' else 0),
                             memory=organ.stats(),
                             probes=dict(controller.last_probes) if kind == 'ocn' else None,
                             temperature=controller.temperature if kind == 'ocn' else None,
                             recent_decisions=controller.cycles[-4:] if kind == 'ocn' else None))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    model = require_model('qwen3.5:9b')
    calls = {'classical': 0, 'ocn': 0}
    results = {}
    for kind in ('classical', 'ocn'):
        def worker(*arguments):
            calls[kind] += 1
            return extract(*arguments)
        results[kind] = scenario(kind, worker, model['digest'])
    output = dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
                  code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  model=model, calls=calls, results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({kind: dict(correct=sum(r['correct'] for r in rows),
                                 attempts=rows[-1]['total_attempts'],
                                 failures=rows[-1]['total_failures'], calls=calls[kind])
                      for kind, rows in results.items()}))


if __name__ == '__main__':
    main()
