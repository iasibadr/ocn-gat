import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ocn_core.adaptive_temperature import OutcomeTemperature
from ocn_core.experience_memory import ExperienceMemory
from ocn_core.experienced_cycle import ExperiencedCycle
from ocn_core.possibility_space import ActionModel


class TemperatureTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'memory'
        self.memory=ExperienceMemory.create(self.path,contract_id='test',actions=['a','b'],capacity=256)
        self.policy=OutcomeTemperature()

    def record(self, event, success, context='c', action='a'):
        return self.memory.record(event_id=event,context=context,action=action,
                                  success=success,quality=int(success),interventions=0,cost=1)

    def test_context_replay_and_reload(self):
        self.record('bad',False)
        hot=self.policy.read(self.memory,'c')
        self.assertGreater(hot['temperature'],self.policy.minimum)
        self.assertFalse(self.record('bad',False))
        restored=ExperienceMemory(self.path,contract_id='test')
        self.assertEqual(hot,self.policy.read(restored,'c'))
        self.assertEqual(self.policy.read(restored,'other')['temperature'],self.policy.minimum)
        for i in range(32):self.record('good'+str(i),True)
        cold=self.policy.read(restored,'c')
        self.assertEqual(cold['observations'],32)
        self.assertEqual(cold['temperature'],self.policy.minimum)

    def test_bounds_and_configuration(self):
        for values in (dict(minimum=0),dict(maximum=.01),dict(rate=0),dict(window=33),dict(rate=True),dict(maximum=float('nan'))):
            with self.assertRaises(ValueError):OutcomeTemperature(**values)
        for i in range(40):self.record(str(i),False)
        t=self.policy.read(self.memory,'c')['temperature']
        self.assertTrue(self.policy.minimum<=t<=self.policy.maximum)

    def test_cycle_feedback_permissions_and_budget(self):
        for a in ('a','b'):
            for i in range(3):self.record(a+str(i),True,action=a)
        cycle=ExperiencedCycle(self.memory,reserve=4,seed=1)
        actions=[ActionModel(a,(0,)*4,0,1,terminal=True) for a in ('a','b')]
        calls=[]
        def observe():return dict(anchor_id='anchor',context='c',state=(0,)*4,authorized={'a'},conditions=())
        def execute(action,*unused):calls.append(action);return 'receipt'
        def verify(*unused):return dict(success=False,quality=0,interventions=0,cost=1,evidence_id='verified')
        args=dict(observe=observe,execute=execute,verify=verify,coordinate_contract='test',
                  minimum=(-1,)*4,maximum=(1,)*4,temperature_policy=self.policy)
        first=cycle.step(actions,**args)
        self.assertEqual(first['status'],'observed')
        self.assertEqual(first['plan']['temperature_regulation']['temperature'],self.policy.minimum)
        second=cycle.step(actions,**args)
        self.assertGreater(second['plan']['temperature_regulation']['temperature'],self.policy.minimum)
        self.assertTrue(all(a=='a' for a in calls))
        self.assertEqual(cycle.probes_remaining,0)
        self.assertEqual(cycle.reserve,4-len(calls))
        options=second['plan']['decision_distribution']
        self.assertNotIn('b',[r['action_id'] for r in options])
        with self.assertRaises(ValueError):cycle.step(actions,decision_temperature=.1,**args)

    def test_unverified_failure_never_heats(self):
        for i in range(3):self.record(str(i),True)
        cycle=ExperiencedCycle(self.memory,reserve=2)
        def broken(*unused):raise RuntimeError('unknown effect')
        result=cycle.step([ActionModel('a',(0,)*4,0,1,terminal=True)],
            observe=lambda:dict(anchor_id='anchor',context='c',state=(0,)*4,authorized={'a'},conditions=()),
            execute=broken,verify=broken,temperature_policy=self.policy,
            coordinate_contract='test',minimum=(-1,)*4,maximum=(1,)*4)
        self.assertEqual(result['status'],'unresolved')
        self.assertEqual(self.policy.read(self.memory,'c')['temperature'],self.policy.minimum)
        self.assertTrue(cycle.halted)

    def test_pending_write_only_changes_temperature_after_record(self):
        for i in range(3):self.record(str(i),True)
        cycle=ExperiencedCycle(self.memory,reserve=2)
        args=dict(observe=lambda:dict(anchor_id='anchor',context='c',state=(0,)*4,authorized={'a'},conditions=()),
            execute=lambda *unused:'receipt',
            verify=lambda *unused:dict(success=False,quality=0,interventions=0,cost=1,evidence_id='verified'),
            temperature_policy=self.policy,coordinate_contract='test',minimum=(-1,)*4,maximum=(1,)*4)
        with patch.object(self.memory,'record',side_effect=OSError('disk')):
            result=cycle.step([ActionModel('a',(0,)*4,0,1,terminal=True)],**args)
        self.assertEqual(result['status'],'memory_pending')
        self.assertEqual(self.policy.read(self.memory,'c')['temperature'],self.policy.minimum)
        cycle.retry_record()
        self.assertGreater(self.policy.read(self.memory,'c')['temperature'],self.policy.minimum)

if __name__=='__main__':unittest.main()
