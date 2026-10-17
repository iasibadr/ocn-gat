import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.experienced_cycle import ExperiencedCycle
from ocn_core.possibility_space import ActionModel

class CycleTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.memory=ExperienceMemory.create(Path(self.tmp.name)/'memory',contract_id='fixture',actions=['read'],capacity=64)
  for i in range(3):self.memory.record(event_id=str(i),context='c',action='read',success=True,quality=1,interventions=0,cost=1)
  self.cycle=ExperiencedCycle(self.memory,reserve=5);self.calls=0
  self.actions=[ActionModel('read',(0,)*4,0,1,terminal=True)]
 def observe(self):return dict(anchor_id='observation-'+str(self.calls),context='c',state=(0,)*4,authorized={'read'},conditions=())
 def execute(self,*args):self.calls+=1;return 'receipt'
 def verify(self,*args):return dict(success=False,quality=0,interventions=0,cost=1,evidence_id='evidence')
 def step(self,**changes):
  args=dict(observe=self.observe,execute=self.execute,verify=self.verify,decision_temperature=.001,coordinate_contract='fixture',minimum=(-1,)*4,maximum=(1,)*4)
  args.update(changes);return self.cycle.step(self.actions,**args)
 def test_actual_failure_updates_memory_not_predicted_success(self):
  r=self.step();self.assertEqual(r['status'],'observed');self.assertEqual(self.calls,1)
  self.assertEqual(self.memory.estimate('c','read')['expected_return'],.75)
  self.assertEqual(r['after']['anchor_id'],'observation-1');self.assertEqual(self.cycle.reserve,4)
 def test_unknown_context_and_forbidden_action_do_not_execute(self):
  for change in ({'context':'new'},{'authorized':set()}):
   r=self.step(observe=lambda:{**self.observe(),**change});self.assertEqual(r['actions_executed'],0)
  self.assertEqual(self.calls,0)
 def test_unresolved_effect_blocks_retry_and_learning(self):
  def broken(*args):self.calls+=1;raise RuntimeError('lost receipt')
  r=self.step(execute=broken);self.assertEqual(r['status'],'unresolved');self.assertIsNone(r['actions_executed']);self.assertEqual(r['execution_attempts'],1)
  with self.assertRaises(RuntimeError):self.step()
  self.assertEqual(self.calls,1);self.assertEqual(self.memory.estimate('c','read')['observations'],3)
 def test_memory_retry_never_reexecutes(self):
  with patch.object(self.memory,'record',side_effect=OSError('disk')):r=self.step()
  self.assertEqual(r['status'],'memory_pending')
  with self.assertRaises(RuntimeError):self.step()
  self.cycle.retry_record();self.assertEqual(self.calls,1)
  self.assertEqual(self.memory.estimate('c','read')['observations'],4)
 def test_real_cost_breach_is_recorded_and_stops_next_action(self):
  def expensive(*args):return {**self.verify(), 'cost':7}
  r=self.step(verify=expensive);self.assertEqual(r['status'],'cost_breach');self.assertEqual(self.cycle.reserve,-2)
  with self.assertRaises(RuntimeError):self.step()
  self.assertEqual(self.memory.estimate('c','read')['observations'],4)
 def test_invalid_post_observation_does_not_enter_memory(self):
  def observe_after_effect():
   return self.observe() if self.calls==0 else {**self.observe(),'state':(float('nan'),0,0,0)}
  r=self.step(observe=observe_after_effect);self.assertEqual(r['status'],'unresolved')
  self.assertEqual(self.calls,1);self.assertEqual(self.memory.estimate('c','read')['observations'],3)
if __name__=='__main__':unittest.main()
