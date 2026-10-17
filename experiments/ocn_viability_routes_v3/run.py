"""VR-3: quarantine recently failed routes without suppressing safe recovery."""
import argparse
from copy import deepcopy
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
from experiments.ocn_probe_lease_v2.run import (
    LeasedAlert, LeasedRiskClassic, LeasedValue, FIELDS, QUESTION, TEXTS)

HERE = Path(__file__).resolve().parent
STAGES = {
    'silence_retablissement': ('initial','drop_A_primary',*('quiet',)*3,
        'restore_A_primary_silent','drop_A_mirror_silent','quiet','quiet',
        'restore_A_mirror_alert','drop_A_primary_alert','restore_A_primary_alert'),
    'signaux_incertains': ('initial',*('alert_A',)*4,'change_B_alert','quiet','quiet',
        'restore_B_silent','drop_B_mirror_alert','restore_B_mirror_silent',
        'change_B_silent','restore_B_alert'),
    'indisponibilite': ('initial','move_A_mirror_alert','drop_A_primary_silent',
        'change_A_mirror_alert','quiet','restore_A_mirror_alert',
        'restore_A_primary_silent','alert_A','alert_A'),
}


class ViabilityRoutes(LeasedValue):
    def __init__(self, routes):
        super().__init__(routes)
        self.bad_until = {doc:{name:-1 for name in self.names} for doc in self.pinned}
        self.route_choices = []

    def _learn_route(self, doc, route, good):
        self.bad_until[doc][route] = -1 if good else self.request_index+2

    def observe(self, changed):
        event = super().observe(changed)
        if changed is not None:
            for route, good in event.get('observations',{}).items():
                self._learn_route(changed,route,good)
        return event

    def _priority_read(self, doc, first, discovery_bytes):
        original = self.routes
        self.routes = {n:original[n] for n in (first,*[n for n in self.names if n!=first])}
        before = self.attempts
        try:
            return RouteAdapter.read(self,doc,discovery_bytes=discovery_bytes)
        finally:
            self.routes = original
            receipts = self.events[-(self.attempts-before):] if self.attempts>before else []
            for event in receipts:
                self._feedback(doc,event['route'],event['status']=='value')
                if event['status']=='value':
                    self.last_success[doc] = event['route']
            self.route_choices.append(dict(document=doc,mode='one_viable',first=first,
                receipts=[dict(route=e['route'],status=e['status']) for e in receipts]))

    def read(self, document_id, *, discovery_bytes=None):
        if document_id not in self.pinned:
            raise ValueError('Unknown document identifier')
        before = self.attempts
        viable = [n for n in self.names if self.bad_until[document_id][n]<self.request_index]
        try:
            if document_id in self.lease:
                return LeasedValue.read(self,document_id,discovery_bytes=discovery_bytes)
            if len(viable)==1:
                return self._priority_read(document_id,viable[0],discovery_bytes)
            return LeasedValue.read(self,document_id,discovery_bytes=discovery_bytes)
        finally:
            receipts = self.events[-(self.attempts-before):] if self.attempts>before else []
            for event in receipts:
                self._learn_route(document_id,event['route'],event['status']=='value')


def mutate(base, stage):
    if stage in ('drop_A_primary','drop_A_primary_silent','drop_A_primary_alert'):
        (base/'primary/A.txt').unlink()
        return 'A' if stage.endswith('alert') else None
    if stage in ('restore_A_primary_silent','restore_A_primary_alert'):
        (base/'primary/A.txt').write_text(TEXTS['A'])
        return 'A' if stage.endswith('alert') else None
    if stage == 'drop_A_mirror_silent':
        (base/'mirror/A.txt').unlink()
        return None
    if stage == 'move_A_mirror_alert':
        target = base/'mirror/archive'
        target.mkdir()
        (base/'mirror/A.txt').rename(target/'moved.txt')
        return 'A'
    if stage == 'change_A_mirror_alert':
        (base/'mirror/archive/moved.txt').write_text('Shipment S has origin Meknes.\n')
        return 'A'
    if stage == 'restore_A_mirror_alert':
        target = base/'mirror/archive/moved.txt'
        if not target.exists():
            target = base/'mirror/A.txt'
        target.write_text(TEXTS['A'])
        return 'A'
    if stage in ('change_B_alert','change_B_silent'):
        (base/'primary/B.txt').write_text('Shipment S has destination Rabat.\n')
        return 'B' if stage.endswith('alert') else None
    if stage in ('restore_B_silent','restore_B_alert'):
        (base/'primary/B.txt').write_text(TEXTS['B'])
        return 'B' if stage.endswith('alert') else None
    if stage == 'drop_B_mirror_alert':
        (base/'mirror/B.txt').unlink()
        return 'B'
    if stage == 'restore_B_mirror_silent':
        (base/'mirror/B.txt').write_text(TEXTS['B'])
        return None
    if stage == 'alert_A':
        return 'A'
    return None


def episode(name, policy, worker, revision):
    rows = []
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        routes = {}
        for route in ('primary','mirror'):
            root = base/route
            root.mkdir()
            adapter = DocumentAdapter(root,base/(route+'.json'))
            for doc, content in TEXTS.items():
                (root/(doc+'.txt')).write_text(content)
                adapter.bind(doc,doc+'.txt')
            routes[route] = adapter
        controller = (RouteAdapter(routes,policy='sticky') if policy=='sticky' else
                      LeasedAlert(routes) if policy=='alert_classic' else
                      LeasedRiskClassic(routes) if policy=='risk_classic' else
                      ViabilityRoutes(routes))
        organ = ExtractionOrgan(worker,lambda:revision,max_cells=2,
                                entries_per_cell=4,max_reuses=16)
        agent = EvidenceAgent(controller,organ,extract_many=organ.extract_many)
        for index,stage in enumerate(STAGES[name]):
            alert = mutate(base,stage)
            if policy!='sticky':
                controller.begin_request(index)
                watch = controller.observe(alert)
            else:
                watch = dict(action='skip')
            before = (controller.attempts,controller.failures)
            try:
                response = agent.answer(QUESTION,FIELDS,('A','B'))
                error = None
            except (ValueError,OSError) as exc:
                response = None
                error = type(exc).__name__+': '+str(exc)
            expected_refusal = name=='indisponibilite' and index in (3,4)
            valid_refusal = response is None and error is not None and \
                'Pinned version unavailable on all authorized routes' in error
            correct = valid_refusal if expected_refusal else (
                response is not None and not response['abstain'] and
                response['values']=={'origin':'Taza','destination':'Fes'})
            attempts = controller.attempts-before[0]
            score = (1. if expected_refusal and valid_refusal else
                     1. if correct and attempts<=4 else .5 if correct else 0.)
            if policy!='sticky':
                lease_events = list(controller.lease_events)
                controller.end_request()
            else:
                lease_events = []
            if policy in ('risk_classic','ocn_viability'):
                controller.regulate(correct)
            rows.append(dict(index=index,stage=stage,alert=alert,watch=watch,
                lease_events=lease_events,correct=correct,score=score,
                task_attempts=attempts,task_failures=controller.failures-before[1],
                probes=getattr(controller,'probe_attempts',0),
                probe_failures=getattr(controller,'probe_failures',0),
                route_state=deepcopy(controller.bad_until) if policy=='ocn_viability' else None,
                response=None if response is None else dict(values=response['values'],
                    paths=response['source_paths'],abstain=response['abstain']),
                error=error,memory=organ.stats()))
    probes = rows[-1]['probes']
    return dict(rows=rows,exact=sum(r['correct'] for r in rows),
                timely=sum(r['correct'] and r['task_attempts']<=4 for r in rows),
                task_attempts=sum(r['task_attempts'] for r in rows),
                task_failures=sum(r['task_failures'] for r in rows),
                probes=probes,probe_failures=rows[-1]['probe_failures'],
                net_value=round(sum(r['score'] for r in rows)-.05*probes,6))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    model = require_model('qwen3.5:9b')
    results,calls = {},{}
    for name in STAGES:
        results[name] = {}
        for policy in ('sticky','alert_classic','risk_classic','ocn_viability'):
            count = [0]
            def worker(*params):
                count[0] += 1
                return extract(*params)
            results[name][policy] = episode(name,policy,worker,model['digest'])
            calls[name+'/'+policy] = count[0]
    output = dict(protocol_commit='994240c',
        protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        model=model,calls=calls,results=results)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({n:{p:{k:v for k,v in r.items() if k!='rows'}
                         for p,r in a.items()} for n,a in results.items()}))


if __name__=='__main__':
    main()
