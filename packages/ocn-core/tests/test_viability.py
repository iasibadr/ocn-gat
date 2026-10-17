import itertools
import unittest
import numpy as np
from ocn_core.controller import left
from ocn_core.viability import transition_envelope,admissible


class ViabilityTests(unittest.TestCase):
    def test_all_box_corners_and_error_signs_are_enclosed(self):
        rng=np.random.default_rng(4)
        for activation in ('linear','tanh'):
            for _ in range(10):
                a=rng.normal(size=(4,4));z=rng.normal(size=4);r=rng.uniform(0,.3,4)
                b=rng.normal(size=4);error=np.full(4,.04)
                envelope=transition_envelope(a,z,r,bias=b,model_error=error,activation=activation)
                for signs in itertools.product((-1,1),repeat=4):
                    value=a@(z+r*np.array(signs))+b
                    if activation=='tanh':value=np.tanh(value)
                    self.assertTrue(np.all(value-error>=np.array(envelope.lower)-1e-12))
                    self.assertTrue(np.all(value+error<=np.array(envelope.upper)+1e-12))

    def test_local_derivative_does_not_replace_finite_uncertainty(self):
        envelope=transition_envelope(np.eye(4),[2]*4,[2]*4,activation='tanh')
        linear_lower=np.array(envelope.mean)-np.array(envelope.jacobian)@np.full(4,2)
        self.assertGreater(linear_lower[0],envelope.lower[0]+.5)
        self.assertFalse(admissible(envelope,[.5]*4,[1]*4,reserve=10,cost_upper=1,reserve_floor=1))

    def test_reserve_and_state_margins_are_both_required(self):
        e=transition_envelope(np.eye(4),[.5]*4,[.1]*4)
        self.assertTrue(admissible(e,[0]*4,[1]*4,reserve=3,cost_upper=2,reserve_floor=1))
        self.assertFalse(admissible(e,[0]*4,[1]*4,reserve=3,cost_upper=2.01,reserve_floor=1))
        self.assertFalse(admissible(e,[0]*4,[1]*4,reserve=3,cost_upper=1,reserve_floor=1,margin=.45))

    def test_hamilton_matrix_uses_the_same_sensitivities(self):
        a=left(np.array([.4,.1,-.2,.3]));z=np.array([.1,.2,.3,.4]);eps=1e-6
        e=transition_envelope(a,z,[0]*4,activation='tanh')
        numeric=np.column_stack([(np.tanh(a@(z+eps*v))-np.tanh(a@(z-eps*v)))/(2*eps) for v in np.eye(4)])
        np.testing.assert_allclose(e.jacobian,numeric,atol=1e-9)

    def test_invalid_and_overflowed_predictions_fail_closed(self):
        for radius in ([0,0,0,-1],[0,0,0,float('nan')],[1,2]):
            with self.assertRaises(ValueError):transition_envelope(np.eye(4),[0]*4,radius)
        with self.assertRaises(ValueError):transition_envelope(np.full((4,4),1e308),[2]*4,[0]*4)
        with self.assertRaises(ValueError):transition_envelope(np.eye(4),[0]*4,[0]*4,activation='unknown')
        e=transition_envelope(np.eye(4),[0]*4,[0]*4)
        with self.assertRaises(ValueError):admissible(e,[0]*4,[1]*4,reserve=10,cost_upper=-1,reserve_floor=0)


if __name__=='__main__':unittest.main()
