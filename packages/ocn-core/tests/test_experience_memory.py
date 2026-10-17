from pathlib import Path
import tempfile
import unittest
import json
import subprocess
import sys
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from ocn_core.experience_memory import ExperienceMemory


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'memory.sqlite'
        self.m=ExperienceMemory.create(self.path,contract_id='documents-v1',actions=['quick','deep'],capacity=4)

    def record(self,event='one',**kw):
        values=dict(event_id=event,context='synthesis',action='deep',success=True,quality=.9,interventions=1,cost=7.)
        values.update(kw);return self.m.record(**values)

    def test_restart_and_revaluation_preserve_observations(self):
        self.record()
        reopened=ExperienceMemory(self.path,contract_id='documents-v1')
        self.assertEqual(reopened.estimate('synthesis','deep')['expected_return'],1)
        self.assertAlmostEqual(reopened.estimate('synthesis','deep',success_weight=0,quality_weight=1)['expected_return'],.9)
        self.assertEqual(reopened.estimate('synthesis','deep',intervention_penalty=2)['expected_return'],-1)
        self.assertEqual(reopened.estimate('synthesis','deep')['observations'],1)

    def test_event_replay_is_idempotent_and_conflict_rejected(self):
        self.assertTrue(self.record());self.assertFalse(self.record())
        with self.assertRaises(ValueError):self.record(quality=.1)
        self.assertEqual(self.m.estimate('synthesis','deep')['observations'],1)

    def test_failure_changes_estimate_without_forgetting_other_context(self):
        self.record();self.record('failure',success=False,quality=0)
        self.assertEqual(self.m.estimate('synthesis','deep')['expected_return'],.75)
        self.assertIsNone(self.m.estimate('new-context','deep')['expected_return'])
        self.assertIsNone(self.m.estimate('synthesis','quick')['expected_return'])

    def test_capacity_does_not_silently_discard_experience(self):
        for n in range(4):self.record(str(n))
        with self.assertRaisesRegex(ValueError,'capacity'):self.record('overflow')
        self.assertFalse(self.record('0'))

    def test_contract_and_missing_store_fail_closed(self):
        with self.assertRaises(ValueError):ExperienceMemory(self.path,contract_id='different')
        with self.assertRaises(sqlite3.OperationalError):ExperienceMemory(self.path.parent/'missing',contract_id='documents-v1')
        self.assertFalse((self.path.parent/'missing').exists())
        with self.assertRaises(FileExistsError):ExperienceMemory.create(self.path,contract_id='documents-v1',actions=['x'])

    def test_cost_is_recorded_but_not_implicit_reward_penalty(self):
        self.record(cost=1e6)
        self.assertEqual(self.m.estimate('synthesis','deep')['expected_return'],1)
        with self.assertRaises(ValueError):self.record('bad',quality=float('nan'))
        with self.assertRaises(ValueError):self.record('bad',action='unknown')

    def test_unknown_cost_is_not_rewritten_as_zero(self):
        self.assertTrue(self.record(cost=None))
        self.assertFalse(self.record(cost=None))
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.record(cost=0)
        self.assertEqual(self.m.estimate('synthesis','deep')['expected_return'],1)

    def test_new_process_reads_committed_observation(self):
        self.record()
        code='''import json,sys
from ocn_core.experience_memory import ExperienceMemory
m=ExperienceMemory(sys.argv[1],contract_id='documents-v1')
print(json.dumps(m.estimate('synthesis','deep')))
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.path)],capture_output=True,text=True,timeout=15,check=True)
        value=json.loads(result.stdout)
        self.assertEqual(value['observations'],1)
        self.assertEqual(value['expected_return'],1.)

    def test_concurrent_capacity_reservation_does_not_overfill(self):
        for n in range(3):self.record(str(n))
        barrier=Barrier(4)
        def attempt(n):
            barrier.wait(timeout=10)
            try:return self.record('parallel-'+str(n))
            except ValueError as exc:
                if 'capacity' not in str(exc):raise
                return False
        with ThreadPoolExecutor(max_workers=4) as executor:
            results=list(executor.map(attempt,range(4)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.m.estimate('synthesis','deep')['observations'],4)

    def test_concurrent_replays_count_once(self):
        barrier=Barrier(4)
        def replay(_):
            barrier.wait(timeout=10)
            return self.record('same-event')
        with ThreadPoolExecutor(max_workers=4) as executor:
            results=list(executor.map(replay,range(4)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.m.estimate('synthesis','deep')['observations'],1)

    def test_process_death_before_commit_does_not_create_experience(self):
        self.record('committed')
        code='''import os,sys
from contextlib import contextmanager
from ocn_core.experience_memory import ExperienceMemory
original=ExperienceMemory.connect
@contextmanager
def interrupted(self):
    with original(self) as db:
        def before_statement(sql):
            if sql.strip().upper()=='COMMIT':os._exit(61)
        db.set_trace_callback(before_statement)
        yield db
ExperienceMemory.connect=interrupted
m=ExperienceMemory(sys.argv[1],contract_id='documents-v1')
m.record(event_id='interrupted',context='synthesis',action='deep',success=False,quality=0.,interventions=0,cost=1.)
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.path)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,61,result.stderr)
        self.assertEqual(self.m.estimate('synthesis','deep')['observations'],1)
        self.assertEqual(self.m.estimate('synthesis','deep')['expected_return'],1.)
        self.assertTrue(self.record('interrupted',success=False,quality=0.,interventions=0,cost=1.))
        self.assertEqual(self.m.estimate('synthesis','deep')['observations'],2)


if __name__=='__main__':unittest.main()
