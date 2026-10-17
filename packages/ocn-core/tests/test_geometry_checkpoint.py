import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from ocn_core.geometry_learning import GeometryLearner
from ocn_core.geometry_checkpoint import save_geometry, load_geometry


class GeometryCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'state.json'
        self.contract='normalized-fixture-v1'
        self.learner=GeometryLearner(2)
        rng=np.random.default_rng(61)
        for _ in range(20):
            x=rng.uniform(-1,1,(2,4));self.learner.predict(x);self.learner.observe(np.tanh(-x))

    def test_new_process_resumes_pending_prediction_and_learning(self):
        x=[[.1,.2,.3,.4],[.4,.3,.2,.1]]
        self.learner.predict(x)
        save_geometry(self.learner,self.path,contract_id=self.contract)
        expected=self.learner.observe(x)
        code='''import json,sys
from ocn_core.geometry_checkpoint import load_geometry,save_geometry
a=load_geometry(sys.argv[1],contract_id=sys.argv[2])
print(json.dumps(a.observe(json.loads(sys.argv[3]))))
save_geometry(a,sys.argv[1],contract_id=sys.argv[2])
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.path),self.contract,json.dumps(x)],
            check=True,text=True,capture_output=True,timeout=15)
        self.assertEqual(json.loads(result.stdout),expected)
        recovered=load_geometry(self.path,contract_id=self.contract)
        self.assertEqual(recovered.observations,21)
        with self.assertRaises(RuntimeError):recovered.observe(x)
        np.testing.assert_array_equal(recovered.predict(x)['prediction'],self.learner.predict(x)['prediction'])

    def test_bad_contract_corruption_and_symlink_are_refused(self):
        save_geometry(self.learner,self.path,contract_id=self.contract)
        with self.assertRaises(ValueError):load_geometry(self.path,contract_id='other-scales')
        raw=self.path.read_bytes();value=json.loads(raw)
        mutations=[('scores',[float('nan'),0,0]),('scores',[-1,0,0]),('observations',True),
                   ('parameters',[[[9]*4]*2]*3),('pending_coordinates',[[3]*4]*2)]
        for key,bad in mutations:
            changed=dict(value);changed[key]=bad;self.path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):load_geometry(self.path,contract_id=self.contract)
        self.path.write_bytes(b'{"format":"x",'+raw[1:])
        with self.assertRaises(ValueError):load_geometry(self.path,contract_id=self.contract)
        self.path.write_bytes(raw)
        link=self.path.with_name('alias');link.symlink_to(self.path)
        with self.assertRaises(OSError):load_geometry(link,contract_id=self.contract)
        with self.assertRaises(ValueError):save_geometry(self.learner,link,contract_id=self.contract)

    def test_failed_pre_replace_sync_preserves_previous_checkpoint(self):
        save_geometry(self.learner,self.path,contract_id=self.contract)
        before=self.path.read_bytes()
        self.learner.predict([[0]*4]*2)
        with patch('ocn_core.geometry_checkpoint.os.fsync',side_effect=OSError('injected')):
            with self.assertRaises(OSError):save_geometry(self.learner,self.path,contract_id=self.contract)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.glob('.geometry-*')),[])


if __name__=='__main__':unittest.main()
