import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import Agent,DNA,DirectoryHabitat,CompactAgent,CompactDNA,CompactReservoir,DissipativeHabitat,save_checkpoint,load_checkpoint

class DeferredTests(unittest.TestCase):
    def test_same_task_trajectory_and_bounded_maintenance(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();dna=CompactDNA(max_calls=3,max_cache=1,source_ids=('one',),emission_phase='after',retirement_capacity=2)
            a=CompactAgent('ocn_hamilton',{'one':'data0'},dna,seed=5)
            plain=Agent('ocn_hamilton',{'one':'data0'},DNA(max_calls=3,max_cache=1,source_ids=('one',)),seed=5)
            sink=CompactReservoir(p/'sink',2);emitted=0
            previous=None
            for n in range(30):
                name=f'data{n//3}'
                if previous and previous!=name:(h/previous).unlink()
                previous=name
                (h/name).write_text(json.dumps(dict(source='one',step=n,value=n)))
                (h/'directory.json').write_text(json.dumps({'one':name}))
                (h/'schemas.json').write_text(json.dumps({'one':{'codec':'integer','value_path':['value']}}))
                if n%4==0:sink.drain(1)
                tools=DissipativeHabitat(h,dna,sink)
                expected=plain.step(n,DirectoryHabitat(h,plain.dna));result=a.step(n,tools)
                self.assertEqual(result['output'],expected['output']);self.assertEqual(result['decisions'],expected['decisions'])
                result=a.finish_request(n,tools,p/'state')
                self.assertLessEqual(result['cost'],3)
                self.assertEqual(result['cost'],len(result['calls']))
                emitted+=sum(c['operation']=='dissipate' for c in result['calls'])
                a=load_checkpoint(p/'state',dna,'ocn_hamilton')
            self.assertGreater(emitted,0);self.assertGreater(a.retirement['accepted_events'],0)

    def test_save_before_sink_and_resume_after_lost_final_save(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();dna=CompactDNA(max_calls=5,max_cache=1,source_ids=('one',),emission_phase='after')
            a=CompactAgent('reactive',{'one':'old'},dna);sink=CompactReservoir(p/'sink',4)
            (h/'new').write_text(json.dumps(dict(source='one',step=0,value=1)))
            (h/'directory.json').write_text(json.dumps({'one':'new'}))
            tools=DissipativeHabitat(h,dna,sink);a.step(0,tools)
            count=0
            def save_then_fail(agent,path):
                nonlocal count
                count+=1
                if count==2:raise OSError('lost final checkpoint')
                save_checkpoint(agent,path)
            with patch('ocn_core.checkpoint.save_checkpoint',side_effect=save_then_fail):
                with self.assertRaises(OSError):a.finish_request(0,tools,p/'state')
            recovered=load_checkpoint(p/'state',dna,'reactive')
            self.assertEqual(recovered.retirement['accepted'],0);self.assertEqual(sink.status()['load'],1)
            self.assertTrue(recovered.retirement['pending'][0]['sealed'])
            frozen=recovered.retirement['pending'][0].copy()
            recovered.replace_memory('paths','one','stale',1)
            self.assertEqual(recovered.retirement['pending'][0],frozen)
            (h/'new').write_text(json.dumps(dict(source='one',step=1,value=2)))
            tools=DissipativeHabitat(h,dna,sink);recovered.step(1,tools);recovered.finish_request(1,tools,p/'state')
            self.assertEqual(sink.status()['load'],1);self.assertEqual(recovered.retirement['accepted'],1)

if __name__=='__main__':unittest.main()
