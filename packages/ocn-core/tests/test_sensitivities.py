import json
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
from ocn_core import Agent,DNA,DirectoryHabitat,prediction_jacobian,action_entropy
from ocn_core.controller import Predictor

class SensitivityTests(unittest.TestCase):
    def test_all_entries_against_finite_differences(self):
        rng=np.random.default_rng(29);u=rng.normal(size=4);prior=rng.normal(size=(4,4))
        for policy in ('classical_learner','ocn_hamilton','ocn_real'):
            m=Predictor(policy);m.a[:]=rng.normal(size=(4,4));m.w[:]=rng.normal(size=(4,4,4));m.b[:]=rng.normal(size=(4,4))
            for order in ((0,1,2,3),(2,0,3,1)):
                for conjugate in (False,True):
                    sign=np.array([1,-1,-1,-1]) if conjugate else np.ones(4)
                    for action in range(4):
                        def f(x):return sign*(m.predict(x[list(order)])[action]+prior@x)
                        estimated=np.column_stack([(f(u+np.eye(4)[j]*1e-5)-f(u-np.eye(4)[j]*1e-5))/(2e-5) for j in range(4)])
                        exact=prediction_jacobian(m,action,input_order=order,prior_jacobian=prior,conjugate_output=conjugate)
                        np.testing.assert_allclose(exact,estimated,atol=1e-9,rtol=1e-9)

    def test_optional_trace_before_update_and_no_decision_change(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);dna=DNA(source_ids=('s',),max_calls=4)
            a=Agent('ocn_hamilton',{'s':'s'},dna);b=Agent('ocn_hamilton',{'s':'s'},dna)
            a.capture_sensitivities=True
            (p/'directory.json').write_text(json.dumps({'s':'s'}))
            (p/'schemas.json').write_text(json.dumps({'s':dict(codec='integer',value_path=['value'])}))
            for n in range(8):
                (p/'s').write_text(json.dumps(dict(source='s',step=n,value=n)))
                before_a=a.model.a.copy();before_w=a.model.w.copy()
                ra=a.step(n,DirectoryHabitat(p,dna));rb=b.step(n,DirectoryHabitat(p,dna))
                for decision in ra['decisions']:
                    diagnostic=decision.pop('sensitivities');m=Predictor('ocn_hamilton');m.a[:]=before_a;m.w[:]=before_w
                    prior=np.zeros((4,4));prior[3,3]=1
                    order=tuple(int(i) for i in np.roll(np.arange(4),-decision['anchor']))
                    expected=prediction_jacobian(m,decision['action'],input_order=order,prior_jacobian=prior)
                    np.testing.assert_allclose(diagnostic['jacobian'],expected)
                    np.testing.assert_allclose(diagnostic['conjugated_jacobian'],np.diag([1,-1,-1,-1])@expected)
                    np.testing.assert_allclose(diagnostic['score_gradient'],-expected[0]+.1*expected[1]+.02*expected[3])
                self.assertEqual(ra,rb)
                np.testing.assert_array_equal(a.model.a,b.model.a)

    def test_entropy_and_invalid_parameters(self):
        self.assertAlmostEqual(action_entropy([.25]*4),math.log(4))
        self.assertEqual(action_entropy([1,0,0,0]),0)
        for bad in ([],[.3,.3],[-1,2],[float('nan')],[float('inf')]):
            with self.assertRaises(ValueError):action_entropy(bad)
        m=Predictor('ocn_hamilton')
        for kwargs in ({'input_order':(0,0,2,3)},{'prior_jacobian':np.zeros((3,4))},{'prior_jacobian':np.full((4,4),np.nan)}):
            with self.assertRaises(ValueError):prediction_jacobian(m,0,**kwargs)

if __name__=='__main__':unittest.main()
