import copy
import unittest
import numpy as np
from ocn_core.geometry_learning import GeometryLearner, BASIS


class GeometryLearningTests(unittest.TestCase):
    def test_prediction_precedes_observation_and_missing_is_not_rewarded(self):
        a=GeometryLearner();b=GeometryLearner();x=[[.2,.3,-.1,.4]]
        with self.assertRaises(RuntimeError):a.observe(x)
        prediction=a.predict(x)
        prediction['prediction'][:]=99
        prediction['past_losses'][:]=99
        with self.assertRaises(RuntimeError):a.predict(x)
        with self.assertRaises(ValueError):a.observe([[2,0,0,0]])
        a.discard()
        self.assertEqual(a.observations,0)
        np.testing.assert_array_equal(a.predict(x)['prediction'],b.predict(x)['prediction'])
        self.assertEqual(a.observe(x),b.observe(x))
        with self.assertRaises(RuntimeError):a.observe(x)

    def test_hamilton_signs_and_sixteen_finite_difference_sensitivities(self):
        eye=np.eye(4)
        for index in (1,2,3):np.testing.assert_array_equal(BASIS[index]@BASIS[index],-eye)
        np.testing.assert_array_equal(BASIS[1]@BASIS[2],BASIS[3])
        np.testing.assert_array_equal(BASIS[2]@BASIS[1],-BASIS[3])
        np.testing.assert_array_equal(BASIS[1]@BASIS[2]@BASIS[3],-eye)
        a=GeometryLearner();rng=np.random.default_rng(83)
        for _ in range(40):
            x=rng.uniform(-.7,.7,(1,4));a.predict(x);a.observe(np.tanh(x[:,::-1]))
        x=np.array([[.2,-.4,.5,.1]])
        reference=copy.deepcopy(a).predict(x)
        derivative=np.zeros((4,4));eps=1e-6
        for col in range(4):
            plus=x.copy();minus=x.copy();plus[0,col]+=eps;minus[0,col]-=eps
            derivative[:,col]=(copy.deepcopy(a).predict(plus)['prediction'][0]-
                               copy.deepcopy(a).predict(minus)['prediction'][0])/(2*eps)
        np.testing.assert_allclose(derivative,reference['sensitivities'][0],atol=1e-9,rtol=0)

    def test_invalid_coordinates_and_learning_parameters_are_rejected(self):
        for units in (0,65,True):
            with self.assertRaises(ValueError):GeometryLearner(units)
        for rate in (0,2,float('nan'),True):
            with self.assertRaises(ValueError):GeometryLearner(score_rate=rate)
        a=GeometryLearner()
        for x in ([0,0,0,0],[[True]*4],[[float('inf'),0,0,0]],[[1.1,0,0,0]], [['0']*4]):
            with self.assertRaises(ValueError):a.predict(x)
        self.assertEqual(a.observations,0)


if __name__=='__main__':unittest.main()
