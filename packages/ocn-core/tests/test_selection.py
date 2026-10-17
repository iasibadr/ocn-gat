import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from ocn_core import CompactAgent,CompactDNA,DissipativeHabitat,CompactReservoir,save_checkpoint,load_checkpoint

class SelectionTests(unittest.TestCase):
    def test_eager_summary_and_frozen_boundary(self):
        dna=CompactDNA(max_calls=5,max_cache=1,source_ids=('one',),aggregation='eager')
        a=CompactAgent('reactive',{'one':'a'},dna)
        for name in ('b','c','d'):a.replace_memory('paths','one',name,0)
        self.assertEqual(len(a.retirement['pending']),1);self.assertEqual(a.retirement['pending'][0]['count'],3)
        a.prepare_emission(a.retirement['pending'][0]);frozen=a.retirement['pending'][0].copy()
        for name in ('e','f'):a.replace_memory('paths','one',name,0)
        self.assertEqual(a.retirement['pending'][0],frozen);self.assertEqual(len(a.retirement['pending']),2)
        self.assertEqual(a.retirement['pending'][1]['count'],2)
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'state';save_checkpoint(a,p);b=load_checkpoint(p,dna,'reactive')
            self.assertEqual(a.retirement,b.retirement)

    def test_unsupported_gate_still_detects_new_capability(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir();dna=CompactDNA(max_calls=6,max_cache=1,source_ids=('one',),known_unsupported_reactive=True,aggregation='eager',emission_phase='after')
            a=CompactAgent('ocn_hamilton',{'one':'data'},dna);sink=CompactReservoir(p/'sink',8)
            for n in range(3):
                if n==1:(h/'data').unlink()
                name='data' if n==0 else 'moved'
                (h/name).write_text(json.dumps(dict(source='one',step=n,value='encoded' if n<2 else 42)))
                (h/'directory.json').write_text(json.dumps({'one':name}))
                (h/'schemas.json').write_text(json.dumps({'one':dict(codec='unknown' if n<2 else 'integer',value_path=['value'])}))
                tools=DissipativeHabitat(h,dna,sink);r=a.step(n,tools);a.finish_request(n,tools,p/'state')
                if n==1:
                    self.assertEqual(r['decisions'][0]['action'],0)
                    self.assertEqual(a.paths['one'],'moved')
                    self.assertEqual(r['decisions'][0]['allowed'],[True,False,False,False])
                if n==2:self.assertEqual(r['output']['sum'],42)
            self.assertTrue(a.action_mask('one',np.ones(4,dtype=bool)).all())

    def test_options_are_in_dna_and_validated(self):
        with self.assertRaises(ValueError):CompactDNA(aggregation='unknown')
        with self.assertRaises(ValueError):CompactDNA(known_unsupported_reactive=1)
        with tempfile.TemporaryDirectory() as root:
            dna=CompactDNA();a=CompactAgent('reactive',dict(zip(dna.source_ids,('a','b','c'))),dna)
            p=Path(root)/'state';save_checkpoint(a,p)
            with self.assertRaises(ValueError):load_checkpoint(p,CompactDNA(aggregation='eager'),'reactive')

if __name__=='__main__':unittest.main()
