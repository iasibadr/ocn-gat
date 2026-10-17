import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from ocn_core import CompactAgent,CompactDNA,DissipativeHabitat,CompactReservoir,save_checkpoint,load_checkpoint

class CellTests(unittest.TestCase):
    def test_learning_and_temperature_stay_local(self):
        dna=CompactDNA(learning_scope='source',temperature_scope='source')
        a=CompactAgent('ocn_hamilton',dict(zip(dna.source_ids,('a','b','c'))),dna)
        b=a.predictor_for('beta');before=b.a.copy()
        m=a.predictor_for('alpha');z=np.ones(4);m.update(z,0,np.ones(4),m.predict(z)[0])
        np.testing.assert_array_equal(b.a,before);self.assertFalse(np.array_equal(m.a,before))
        a.record_temperature('alpha',.2)
        self.assertEqual(a.temperature_for('beta'),.04);self.assertAlmostEqual(a.temperature,.28/3)
        self.assertEqual(sum(x.a.size+x.w.size+x.b.size for x in a.cell_models.values()),288)

    def test_cell_checkpoint_matches_continuous_run(self):
        for learning,temperature in [('source','shared'),('shared','source'),('source','source')]:
            with self.subTest(learning=learning,temperature=temperature),tempfile.TemporaryDirectory() as root:
                p=Path(root);h=p/'h';h.mkdir();dna=CompactDNA(max_calls=12,learning_scope=learning,temperature_scope=temperature,aggregation='eager')
                paths={s:s for s in dna.source_ids}
                a=CompactAgent('ocn_hamilton',paths,dna,seed=9);b=CompactAgent('ocn_hamilton',paths,dna,seed=9)
                sinks=[CompactReservoir(p/f'sink{i}',16) for i in range(2)]
                for n in range(12):
                    desc={}
                    for s in dna.source_ids:
                        unknown=s=='alpha' and 3<=n<8
                        (h/s).write_text(json.dumps(dict(source=s,step=n,value='encoded' if unknown else n)))
                        desc[s]=dict(codec='unknown' if unknown else 'integer',value_path=['value'])
                    (h/'directory.json').write_text(json.dumps(paths));(h/'schemas.json').write_text(json.dumps(desc))
                    ra=a.step(n,DissipativeHabitat(h,dna,sinks[0]));rb=b.step(n,DissipativeHabitat(h,dna,sinks[1]))
                    self.assertEqual(ra,rb)
                    save_checkpoint(b,p/'state');b=load_checkpoint(p/'state',dna,'ocn_hamilton')
                for s in dna.source_ids:np.testing.assert_array_equal(a.predictor_for(s).a,b.predictor_for(s).a)

    def test_invalid_scope_rejected(self):
        with self.assertRaises(ValueError):CompactDNA(learning_scope='any')
        with self.assertRaises(ValueError):CompactDNA(temperature_scope='any')

if __name__=='__main__':unittest.main()
