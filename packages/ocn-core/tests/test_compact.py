import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import CompactAgent,CompactDNA,CompactReservoir,DissipativeHabitat,save_checkpoint,load_checkpoint,Fault

class CompactTests(unittest.TestCase):
    def test_saturated_environment_does_not_block_repair(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();dna=CompactDNA(max_calls=5,max_cache=1,source_ids=('one',),retirement_capacity=2)
            a=CompactAgent('reactive',{'one':'old'},dna);sink=CompactReservoir(p/'sink',1)
            previous=None
            for n in range(80):
                if previous:(h/previous).unlink()
                name=f'data{n}';previous=name
                (h/name).write_text(json.dumps(dict(source='one',step=n,value=n)))
                (h/'directory.json').write_text(json.dumps({'one':name}))
                result=a.step(n,DissipativeHabitat(h,dna,sink))
                self.assertEqual(result['output']['sum'],n);self.assertLessEqual(result['cost'],5)
                self.assertLessEqual(len(a.retirement['pending']),2)
                save_checkpoint(a,p/'state');a=load_checkpoint(p/'state',dna,'reactive')
            self.assertGreater(a.retirement['merges'],0)
            self.assertEqual(a.retirement['retired_events'],80)
            self.assertEqual(a.retirement['accepted_events']+sum(e['count'] for e in a.retirement['pending']),80)

    def test_frozen_batch_and_replay_after_remote_commit(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();dna=CompactDNA(max_calls=5,max_cache=1,source_ids=('one',),retirement_capacity=2)
            a=CompactAgent('reactive',{'one':'old'},dna);sink=CompactReservoir(p/'sink',1)
            a.replace_memory('paths','one','a',0);a.replace_memory('paths','one','b',0)
            # Fill reservoir, then seal the next batch by a refused attempt.
            a.before_request(0,DissipativeHabitat(h,dna,sink));frozen=a.retirement['pending'][0].copy()
            a.replace_memory('paths','one','c',0);a.replace_memory('paths','one','d',0)
            self.assertEqual(frozen,a.retirement['pending'][0]);self.assertEqual(a.retirement['pending'][1]['count'],2)
            save_checkpoint(a,p/'state');sink.drain(1)
            a.before_request(1,DissipativeHabitat(h,dna,sink));load=sink.status()['load']
            b=load_checkpoint(p/'state',dna,'reactive');b.before_request(1,DissipativeHabitat(h,dna,sink))
            self.assertEqual(sink.status()['load'],load);self.assertEqual(a.retirement,b.retirement)

    def test_invalid_count_and_conservation(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);dna=CompactDNA(max_calls=5,max_cache=1,source_ids=('one',),retirement_capacity=2)
            a=CompactAgent('reactive',{'one':'old'},dna);sink=CompactReservoir(p/'sink',1)
            a.replace_memory('paths','one','new',0);event=a.retirement['pending'][0].copy();event['count']=True;event['sealed']=True
            with self.assertRaises(Fault):sink.accept(a.retirement['stream'],event)
            a.retirement['merges']=99
            with self.assertRaises(ValueError):save_checkpoint(a,p/'state')
            with self.assertRaises(ValueError):CompactDNA(retirement_capacity=1)

if __name__=='__main__':unittest.main()
