import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import (DissipativeDNA,DissipativeAgent,DissipativeHabitat,RetirementReservoir,Fault,save_checkpoint,load_checkpoint)

class DissipationTests(unittest.TestCase):
    def fixture(self,root,capacity=2,budget=5,queue=4):
        p=Path(root);h=p/'h';h.mkdir()
        dna=DissipativeDNA(max_calls=budget,max_cache=1,source_ids=('one',),retirement_capacity=queue,emission_limit=2)
        reservoir=RetirementReservoir(p/'sink.sqlite',capacity)
        agent=DissipativeAgent('reactive',{'one':'old.json'},dna)
        return p,h,dna,reservoir,agent

    def prepare(self,h,n):
        (h/'directory.json').write_text(json.dumps({'one':'new.json'}))
        (h/'schemas.json').write_text(json.dumps({'one':{'codec':'integer','value_path':['data','measure']}}))
        (h/'new.json').write_text(json.dumps({'source':'one','step':n,'data':{'measure':42}}))

    def test_retirement_leaves_active_memory_and_costs_calls(self):
        with tempfile.TemporaryDirectory() as root:
            p,h,dna,sink,a=self.fixture(root);self.prepare(h,0)
            r=a.step(0,DissipativeHabitat(h,dna,sink))
            self.assertEqual(r['output']['sum'],42);self.assertEqual(r['cost'],4)
            self.assertEqual(a.paths['one'],'new.json');self.assertEqual(len(a.retirement['pending']),2)
            self.assertNotIn('old.json',json.dumps(a.retirement))
            self.prepare(h,1);r=a.step(1,DissipativeHabitat(h,dna,sink))
            self.assertEqual(r['cost'],3);self.assertEqual(r['dissipation']['accepted'],2)
            self.assertEqual(sink.status()['load'],2);self.assertEqual(a.retirement['pending'],[])

    def test_saturation_backoff_and_external_drain(self):
        with tempfile.TemporaryDirectory() as root:
            p,h,dna,sink,a=self.fixture(root,capacity=1);self.prepare(h,0);a.step(0,DissipativeHabitat(h,dna,sink))
            for n in (1,2,3):
                self.prepare(h,n);r=a.step(n,DissipativeHabitat(h,dna,sink))
            self.assertEqual(r['cost'],1) # At n=3, retry is delayed until n=4.
            self.assertEqual(len(a.retirement['pending']),1);self.assertEqual(a.retirement['pressure'],1)
            sink.drain(1);self.prepare(h,4);r=a.step(4,DissipativeHabitat(h,dna,sink))
            self.assertEqual(r['dissipation']['accepted'],2);self.assertEqual(r['cost'],2)

    def test_restart_after_sink_commit_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as root:
            p,h,dna,sink,a=self.fixture(root);self.prepare(h,0);a.step(0,DissipativeHabitat(h,dna,sink));save_checkpoint(a,p/'state')
            self.prepare(h,1);first=a.step(1,DissipativeHabitat(h,dna,sink))
            # Simulated interruption after durable sink acceptance, before agent save.
            recovered=load_checkpoint(p/'state',dna,'reactive');sink=RetirementReservoir(p/'sink.sqlite',2)
            second=recovered.step(1,DissipativeHabitat(h,dna,sink))
            self.assertEqual(first['output'],second['output']);self.assertEqual(sink.status()['load'],2)
            self.assertEqual(recovered.retirement['accepted'],2);self.assertEqual(recovered.retirement['pending'],[])

    def test_full_queue_refuses_unaccounted_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            p,h,dna,sink,a=self.fixture(root,queue=1);self.prepare(h,0)
            r=a.step(0,DissipativeHabitat(h,dna,sink))
            self.assertEqual(r['errors'][0]['code'],'retirement_full');self.assertEqual(a.descriptors['one']['value_path'],['value'])
            self.assertEqual(len(a.retirement['pending']),1)
            self.prepare(h,1);r=a.step(1,DissipativeHabitat(h,dna,sink))
            self.assertEqual(r['output']['sum'],42);self.assertLessEqual(r['cost'],dna.max_calls)

    def test_stream_conflicts_and_conservation_validation(self):
        with tempfile.TemporaryDirectory() as root:
            p,h,dna,sink,a=self.fixture(root);self.prepare(h,0);a.step(0,DissipativeHabitat(h,dna,sink))
            event=a.retirement['pending'][0];sink.accept(a.retirement['stream'],event)
            with self.assertRaises(Fault):sink.accept('f'*32,event)
            with self.assertRaises(Fault):sink.accept(a.retirement['stream'],dict(sequence=1,digest='0'*64))
            a.retirement['accepted']=1
            with self.assertRaises(ValueError):save_checkpoint(a,p/'bad')

if __name__=='__main__':unittest.main()
