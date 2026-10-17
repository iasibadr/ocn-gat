import tempfile,unittest
from dataclasses import replace
from pathlib import Path
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.experienced_cycle import ExperiencedCycle
from ocn_core.possibility_space import ActionModel

class ProbeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.memory=ExperienceMemory.create(Path(self.tmp.name)/'m',contract_id='fixture',actions=['a','b'],capacity=64)
  self.models=[ActionModel('a',(0,)*4,99,1,terminal=True),ActionModel('b',(0,)*4,99,1,terminal=True)]
  self.observation=dict(anchor_id='observed',context='new',state=(0,)*4,authorized={'a','b'},conditions=())
  self.calls=[]
 def execute(self,action,*args):self.calls.append(action)
 def verify(self,*args):return dict(success=True,quality=1,interventions=0,cost=1,evidence_id='host')
 def step(self,cycle,**kw):
  args=dict(observe=lambda:self.observation,execute=self.execute,verify=self.verify,decision_temperature=.001,coordinate_contract='fixture',minimum=(-1,)*4,maximum=(1,)*4)
  args.update(kw);return cycle.step(self.models,**args)
 def test_default_does_not_authorize_unknown_exploration(self):
  r=self.step(ExperiencedCycle(self.memory,reserve=10));self.assertEqual(r['actions_executed'],0);self.assertEqual(self.calls,[])
 def test_cold_start_observes_both_actions_without_invented_reward(self):
  cycle=ExperiencedCycle(self.memory,reserve=10,probe_budget=6)
  for i in range(6):
   r=self.step(cycle);self.assertEqual(r['selection'],'authorized_probe')
   if i==0:self.assertTrue(all(e['expected_return'] is None for e in r['plan']['reward_estimates']))
  self.assertEqual(self.calls,['a','b','a','b','a','b']);self.assertEqual(cycle.probes_remaining,0)
  r=self.step(cycle);self.assertEqual(r['selection'],'experience_distribution')
 def test_budget_exhaustion_does_not_renew_probes(self):
  cycle=ExperiencedCycle(self.memory,reserve=10,probe_budget=1)
  self.step(cycle);r=self.step(cycle);self.assertEqual(r['actions_executed'],0);self.assertEqual(len(self.calls),1)
 def test_authorization_conditions_geometry_and_reserve_still_apply(self):
  cycle=ExperiencedCycle(self.memory,reserve=.5,probe_budget=6)
  self.assertEqual(self.step(cycle)['actions_executed'],0);self.assertEqual(cycle.probes_remaining,6)
  cycle.reserve=10;self.observation['authorized']={'a'}
  self.models[0]=replace(self.models[0],requires=('missing',))
  self.assertEqual(self.step(cycle)['actions_executed'],0)
  self.models[0]=replace(self.models[0],requires=(),injection=(2,0,0,0))
  self.assertEqual(self.step(cycle)['actions_executed'],0);self.assertEqual(self.calls,[])
 def test_failed_execution_consumes_probe_and_does_not_create_success(self):
  cycle=ExperiencedCycle(self.memory,reserve=10,probe_budget=1)
  def uncertain(*args):raise RuntimeError('effect unknown')
  r=self.step(cycle,execute=uncertain);self.assertEqual(r['status'],'unresolved');self.assertEqual(cycle.probes_remaining,0)
  self.assertEqual(self.memory.estimate('new','a')['observations'],0)
  with self.assertRaises(RuntimeError):self.step(cycle)
 def test_invalid_probe_budgets(self):
  for value in (True,-1,65,1.5):
   with self.assertRaises(ValueError):ExperiencedCycle(self.memory,reserve=10,probe_budget=value)
if __name__=='__main__':unittest.main()
