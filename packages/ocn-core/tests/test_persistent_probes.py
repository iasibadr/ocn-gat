import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.probe_budget import PersistentProbeBudget
from ocn_core.experienced_cycle import ExperiencedCycle
from ocn_core.possibility_space import ActionModel

class PersistentProbeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.memory=ExperienceMemory.create(self.root/'memory',contract_id='m',actions=['a'],capacity=64)
  self.budget=PersistentProbeBudget.create(self.root/'budget',limit=1,memory=self.memory,coordinate_contract='c')
  self.calls=[]
 def cycle(self):return ExperiencedCycle(self.memory,reserve=5,persistent_probes=self.budget)
 def step(self,cycle,**kw):
  args=dict(observe=lambda:dict(anchor_id='o',context='task',state=(0,)*4,authorized={'a'},conditions=()),execute=lambda *a:self.calls.append(a),verify=lambda *a:dict(success=True,quality=1,interventions=0,cost=1,evidence_id='e'),decision_temperature=.001,coordinate_contract='c',minimum=(-1,)*4,maximum=(1,)*4)
  args.update(kw);return cycle.step([ActionModel('a',(0,)*4,0,1,terminal=True)],**args)
 def test_reopening_cycle_does_not_restore_allowance(self):
  def execute(*a):self.assertEqual(self.budget.remaining(),0);self.calls.append(a)
  self.step(self.cycle(),execute=execute)
  self.assertEqual(self.step(self.cycle())['actions_executed'],0);self.assertEqual(len(self.calls),1)
  with self.assertRaises(FileExistsError):PersistentProbeBudget.create(self.root/'budget',limit=1,memory=self.memory,coordinate_contract='c')
 def test_other_contract_and_corrupt_counter_refuse_before_execution(self):
  with self.assertRaises(ValueError):self.step(self.cycle(),coordinate_contract='other')
  (self.root/'budget/model-budget.json').write_text('{"limit":1,"used":false}')
  with self.assertRaises(ValueError):self.cycle()
  self.assertEqual(self.calls,[])
 def test_uncertain_write_cannot_grant_execution(self):
  cycle=self.cycle()
  with patch('ocn_core.model_budget.os.replace',side_effect=OSError('disk')):
   with self.assertRaises(OSError):self.step(cycle)
  self.assertEqual(self.calls,[]);self.assertEqual(self.budget.remaining(),1)
 def test_no_local_budget_overlay(self):
  with self.assertRaises(ValueError):ExperiencedCycle(self.memory,reserve=5,probe_budget=1,persistent_probes=self.budget)
 def test_process_exit_after_reservation_does_not_refund(self):
  code="""import os,sys
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.probe_budget import PersistentProbeBudget
from ocn_core.experienced_cycle import ExperiencedCycle
from ocn_core.possibility_space import ActionModel
m=ExperienceMemory(sys.argv[1],contract_id='m')
b=PersistentProbeBudget(sys.argv[2],limit=1,memory=m,coordinate_contract='c')
c=ExperiencedCycle(m,reserve=5,persistent_probes=b)
c.step([ActionModel('a',(0,)*4,0,1,terminal=True)],observe=lambda:dict(anchor_id='o',context='task',state=(0,)*4,authorized={'a'},conditions=()),execute=lambda *a:os._exit(23),verify=lambda *a:None,decision_temperature=.001,coordinate_contract='c',minimum=(-1,)*4,maximum=(1,)*4)
"""
  r=subprocess.run([sys.executable,'-c',code,str(self.memory.path),str(self.budget.root)],timeout=20,capture_output=True)
  self.assertEqual(r.returncode,23,r.stderr.decode());self.assertEqual(self.budget.remaining(),0)
  self.assertEqual(self.memory.estimate('task','a')['observations'],0)
  self.assertEqual(self.step(self.cycle())['actions_executed'],0)
 def test_concurrent_processes_cannot_spend_the_same_last_probe(self):
  from concurrent.futures import ThreadPoolExecutor
  code="""import sys
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.probe_budget import PersistentProbeBudget
try:
 m=ExperienceMemory(sys.argv[1],contract_id='m')
 b=PersistentProbeBudget(sys.argv[2],limit=1,memory=m,coordinate_contract='c')
 b.reserve()
except RuntimeError:
 sys.exit(7)
"""
  def attempt(_):return subprocess.run([sys.executable,'-c',code,str(self.memory.path),str(self.budget.root)],timeout=30,capture_output=True)
  with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(8)))
  self.assertEqual(sum(r.returncode==0 for r in results),1)
  self.assertTrue(all(r.returncode in (0,7) for r in results),[r.stderr.decode() for r in results])
  self.assertEqual(self.budget.remaining(),0)
 def test_boolean_limit_is_not_an_integer_authority(self):
  path=self.root/'budget/probe-authority.json';authority=json.loads(path.read_text());authority['limit']=True;path.write_text(json.dumps(authority))
  with self.assertRaises(ValueError):self.budget.remaining()
if __name__=='__main__':unittest.main()
