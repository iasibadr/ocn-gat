import unittest
import numpy as np
from ocn_core.controller import Predictor,multiply

class HamiltonKernelTests(unittest.TestCase):
    def test_noncommutative_basis_products(self):
        model=Predictor('ocn_hamilton');model.a[:]=np.eye(4)
        # Each row is 1*z, i*z, j*z, k*z.
        np.testing.assert_array_equal(model.predict(np.array([0.,0.,1.,0.])),
            [[0,0,1,0],[0,0,0,1],[-1,0,0,0],[0,-1,0,0]])
        np.testing.assert_array_equal(model.predict(np.array([0.,1.,0.,0.])),
            [[0,1,0,0],[-1,0,0,0],[0,0,0,-1],[0,0,1,0]])
    def test_exact_reference_products_without_mutation(self):
        rng=np.random.default_rng(374000)
        for policy in ('ocn_hamilton','ocn_fixed'):
            model=Predictor(policy)
            for scale in (1e-6,1.,1e6):
                for _ in range(128):
                    model.a[:]=rng.normal(size=(4,4))*scale;model.b[:]=rng.normal(size=(4,4))*scale
                    z=rng.normal(size=4);before=(model.a.copy(),model.b.copy(),z.copy())
                    expected=np.array([multiply(a,z) for a in model.a])+model.b
                    np.testing.assert_array_equal(model.predict(z),expected)
                    for actual,saved in zip((model.a,model.b,z),before):np.testing.assert_array_equal(actual,saved)

if __name__=='__main__':unittest.main()
