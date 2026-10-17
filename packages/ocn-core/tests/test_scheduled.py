from dataclasses import asdict
import copy
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from ocn_core import ScheduledDNA,ScheduledAgent,CompactDNA,CompactReservoir,DissipativeHabitat,save_checkpoint,load_checkpoint
from ocn_core.checkpoint import snapshot,restore


def document(h,n):
    nested=(n//2)%2==1
    doc=dict(source='s',step=n)
    if nested:doc['data']=dict(measure=n)
    else:doc['value']=n
    (h/'s').write_text(json.dumps(doc))
    (h/'directory.json').write_text(json.dumps({'s':'s'}))
    (h/'schemas.json').write_text(json.dumps({'s':dict(codec='integer',value_path=['data','measure'] if nested else ['value'])}))

class ScheduledTests(unittest.TestCase):
    def test_matches_development_selector_before_service(self):
        package=Path(__file__).resolve().parents[1]
        prototype=runpy.run_path(str(package/'benchmarks/dissipative_latency_v1/scheduler.py'))
        for mode in ('backoff','periodic4','classical_learner','ocn_hamilton','ocn_real'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                p=Path(root);h=p/'h';h.mkdir()
                original=CompactDNA(max_calls=4,source_ids=('s',),emission_limit=1,aggregation='eager',learning_scope='source',known_unsupported_reactive=True)
                dna=ScheduledDNA(**asdict(original),scheduler=mode)
                a=prototype['SchedulerAgent']('reactive',{'s':'s'},original,scheduler=mode,tuning=prototype['Tuning'](True,False))
                b=ScheduledAgent('reactive',{'s':'s'},dna)
                b.retirement['stream']=a.retirement['stream']
                sinks=[CompactReservoir(p/f'sink{i}',2) for i in range(2)]
                for n in range(64):
                    document(h,n)
                    if n%16==0:
                        for sink in sinks:sink.drain(1)
                    ra=a.step(n,DissipativeHabitat(h,original,sinks[0]))
                    rb=b.step(n,DissipativeHabitat(h,dna,sinks[1]))
                    for key in ('output','cost','calls','decisions','dissipation'):self.assertEqual(ra[key],rb[key])
                    self.assertEqual(a.retirement,b.retirement)
                    self.assertLessEqual(len(b.emission_state['born']),dna.retirement_capacity)

    def test_resume_exact_in_both_phases(self):
        for phase in ('before','after'):
            for mode in ('backoff','classical_learner','ocn_hamilton'):
                with self.subTest(phase=phase,mode=mode),tempfile.TemporaryDirectory() as root:
                    p=Path(root);h=p/'h';h.mkdir()
                    dna=ScheduledDNA(max_calls=4,source_ids=('s',),aggregation='eager',emission_phase=phase,scheduler=mode,learning_scope='source')
                    a=ScheduledAgent('reactive',{'s':'s'},dna);b=ScheduledAgent('reactive',{'s':'s'},dna)
                    b.retirement['stream']=a.retirement['stream']
                    sinks=[CompactReservoir(p/f'sink{i}',2) for i in range(2)]
                    for n in range(36):
                        document(h,n)
                        if n%8==0:
                            for sink in sinks:sink.drain(1)
                        results=[]
                        for i,agent in enumerate((a,b)):
                            tools=DissipativeHabitat(h,dna,sinks[i]);r=agent.step(n,tools)
                            if phase=='after':r=agent.finish_request(n,tools,p/f'state{i}')
                            results.append(r)
                        self.assertEqual(*results)
                        save_checkpoint(b,p/'resume');b=load_checkpoint(p/'resume',dna,'reactive')
                        self.assertEqual(snapshot(a),snapshot(b))

    def test_bounded_timestamps_and_rejected_bad_checkpoints(self):
        dna=ScheduledDNA(source_ids=('s',),aggregation='eager',retirement_capacity=2)
        a=ScheduledAgent('reactive',{'s':'old'},dna)
        for n in range(1000):
            a.last_step=n;a.replace_memory('paths','s',f's{n}',n)
            if n==0:a.prepare_emission(a.retirement['pending'][0])
        self.assertEqual(len(a.emission_state['born']),2)
        self.assertEqual(a.retirement['retired_events'],1000)
        payload=json.loads(json.dumps(snapshot(a)))
        self.assertEqual(snapshot(restore(payload,dna,'reactive')),snapshot(a))
        for mutate in (lambda p:p['emission']['state']['born'].update({'9999':0}),
                       lambda p:p['emission']['state'].__setitem__('last_attempt',1001),
                       lambda p:p['emission']['state']['born'].__setitem__('1',1000),
                       lambda p:p['emission']['state']['born'].__setitem__('1',2),
                       lambda p:p['emission']['state'].__setitem__('refusal_ema',float('nan')),
                       lambda p:p['emission']['predictor'].__setitem__('a',[]),
                       lambda p:p['retirement'].__setitem__('backoff',32)):
            bad=copy.deepcopy(payload);mutate(bad)
            with self.assertRaises(ValueError):restore(bad,dna,'reactive')

    def test_wait_does_not_freeze_open_batch_after_service(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();document(h,0)
            dna=ScheduledDNA(max_calls=4,source_ids=('s',),emission_phase='after',aggregation='eager')
            a=ScheduledAgent('reactive',{'s':'s'},dna)
            a.replace_memory('paths','s','missing',0)
            tools=DissipativeHabitat(h,dna,CompactReservoir(p/'sink',2))
            a.step(0,tools)
            a.emission_model.b[:]=-10.
            a.finish_request(0,tools,p/'state')
            self.assertFalse(a.retirement['pending'][0]['sealed'])

    def test_resume_after_accepted_emission_loses_final_save(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();document(h,0)
            dna=ScheduledDNA(max_calls=4,source_ids=('s',),emission_phase='after',scheduler='backoff')
            a=ScheduledAgent('reactive',{'s':'missing'},dna);sink=CompactReservoir(p/'sink',2)
            tools=DissipativeHabitat(h,dna,sink);a.step(0,tools)
            count=0
            def failing_save(agent,path):
                nonlocal count
                count+=1
                if count==2:raise OSError('interrupted after acceptance')
                save_checkpoint(agent,path)
            with patch('ocn_core.checkpoint.save_checkpoint',side_effect=failing_save):
                with self.assertRaises(OSError):a.finish_request(0,tools,p/'state')
            a=load_checkpoint(p/'state',dna,'reactive')
            self.assertEqual(sink.status()['load'],1)
            self.assertTrue(a.retirement['pending'][0]['sealed'])
            self.assertEqual(len(a.emission_state['born']),1)
            document(h,1);tools=DissipativeHabitat(h,dna,sink)
            a.step(1,tools);a.finish_request(1,tools,p/'state')
            self.assertEqual(sink.status()['load'],1)
            self.assertEqual(a.retirement['accepted_events'],1)
            self.assertEqual(a.emission_state['born'],{})

if __name__=='__main__':unittest.main()
