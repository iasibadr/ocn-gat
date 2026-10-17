import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import (RepackingAgent,RepackingDNA,CompactReservoir,DissipativeHabitat,
    ToolSession,load_checkpoint,save_checkpoint)
from ocn_core.checkpoint import snapshot,canonical
from ocn_core.controller import descriptor_digest

class MaintenanceTests(unittest.TestCase):
    def test_due_probe_is_read_only_and_does_not_consume_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root)
            before=canonical(snapshot(agent));disk=(root/'state').read_bytes()
            for step,expected in ((31,False),(32,True),(32,True)):
                tools=DissipativeHabitat(h,agent.dna,sink)
                self.assertEqual(agent.maintenance_due(step,tools),expected)
                self.assertEqual(tools.calls,[]);self.assertEqual(tools.cost,0)
                self.assertEqual(canonical(snapshot(agent)),before)
                self.assertEqual((root/'state').read_bytes(),disk)
            agent.maintain(32,DissipativeHabitat(h,agent.dna,sink),root/'state')
            self.assertFalse(agent.maintenance_due(64,DissipativeHabitat(h,agent.dna,sink)))
            self.assertEqual(agent.last_step,32)

    def test_due_probe_rejects_active_owner_and_honors_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root)
            session=ToolSession(agent,DissipativeHabitat(h,agent.dna,sink),1)
            with self.assertRaises(ValueError):agent.maintenance_due(32,DissipativeHabitat(h,agent.dna,sink))
            session.persist(root/'state')
            agent.retirement['retry_after']=40
            self.assertFalse(agent.maintenance_due(32,DissipativeHabitat(h,agent.dna,sink)))
            self.assertTrue(agent.maintenance_due(40,DissipativeHabitat(h,agent.dna,sink)))

    def test_periodic_override_is_predicted_and_frozen_before_attempt(self):
        import ocn_core.checkpoint as checkpoints
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root,mode='periodic4')
            agent.retirement['retry_after']=8
            tools=DissipativeHabitat(h,agent.dna,sink)
            self.assertTrue(agent.maintenance_due(4,tools))
            original=checkpoints.save_checkpoint;calls=[]
            def save_or_fail(*args):
                calls.append(1)
                if len(calls)==2:raise OSError('after acceptance')
                original(*args)
            with patch('ocn_core.checkpoint.save_checkpoint',side_effect=save_or_fail):
                with self.assertRaises(OSError):agent.maintain(4,tools,root/'state')
            loaded=load_checkpoint(root/'state',agent.dna,'reactive')
            self.assertTrue(loaded.retirement['pending'][0]['sealed'])
            self.assertEqual(sink.status()['load'],1)

    def setup(self,root,capacity=2,mode='paced32'):
        h=root/'h';h.mkdir()
        dna=RepackingDNA(source_ids=('s',),max_cache=1,max_calls=4,require_schema_binding=True,
            scheduler=mode,aggregation='eager',emission_phase='after')
        agent=RepackingAgent('reactive',{'s':'data.json'},dna)
        sink=CompactReservoir(root/'sink',capacity)
        descriptor=dict(codec='integer',value_path=['amount'])
        (h/'schemas.json').write_text(json.dumps({'s':descriptor}))
        (h/'data.json').write_text(json.dumps(dict(source='s',step=0,amount=47,
            schema_digest=descriptor_digest(descriptor))))
        s=ToolSession(agent,DissipativeHabitat(h,dna,sink),0)
        for op,path,value in [('read','data.json',0),('describe','',0),('read','data.json',0),('finish','',47)]:
            s.execute(dict(op=op,path=path,value=value))
        s.persist(root/'state')
        return h,agent,sink

    def test_wait_and_emit_without_task_reads_or_predictor_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root)
            baseline=snapshot(agent)
            for step,complete in ((31,False),(32,True)):
                tools=DissipativeHabitat(h,agent.dna,sink)
                with patch.object(tools,'read',side_effect=AssertionError('No task read')):
                    result=agent.maintain(step,tools,root/'state')
                self.assertEqual(result['maintenance_complete'],complete)
                self.assertFalse(result['task_executed']);self.assertIsNone(result['output'])
                self.assertEqual([c['operation'] for c in tools.calls],['dissipate'] if complete else [])
                current=snapshot(agent)
                for key in ('paths','descriptors','predictor','temperature','last_cost','last_refresh','errors','rng'):
                    self.assertEqual(canonical(current[key]),canonical(baseline[key]))
                agent=load_checkpoint(root/'state',agent.dna,'reactive')
            self.assertEqual(agent.retirement['accepted_events'],1)

    def test_full_sink_keeps_debt_until_external_drain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root,capacity=1)
            agent.maintain(32,DissipativeHabitat(h,agent.dna,sink),root/'state')
            (h/'directory.json').write_text(json.dumps({'s':'next.json'}))
            session=ToolSession(agent,DissipativeHabitat(h,agent.dna,sink),33)
            session.execute(dict(op='locate',path='',value=0))
            session.persist(root/'state')
            refused=agent.maintain(64,DissipativeHabitat(h,agent.dna,sink),root/'state')
            self.assertFalse(refused['maintenance_complete'])
            self.assertEqual(refused['dissipation']['accepted_events'],1)
            self.assertEqual(sink.status()['load'],1)
            sink.drain(1)
            agent=load_checkpoint(root/'state',agent.dna,'reactive')
            accepted=agent.maintain(96,DissipativeHabitat(h,agent.dna,sink),root/'state')
            self.assertTrue(accepted['maintenance_complete'])
            self.assertEqual(accepted['dissipation']['accepted_events'],2)

    def test_active_session_and_repeated_tick_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root)
            s=ToolSession(agent,DissipativeHabitat(h,agent.dna,sink),1)
            with self.assertRaises(ValueError):agent.maintain(32,DissipativeHabitat(h,agent.dna,sink),root/'state')
            s.persist(root/'state')
            agent.maintain(32,DissipativeHabitat(h,agent.dna,sink),root/'state')
            before=(root/'state').read_bytes()
            with self.assertRaises(ValueError):agent.maintain(32,DissipativeHabitat(h,agent.dna,sink),root/'state')
            self.assertEqual((root/'state').read_bytes(),before)

    def test_ack_save_failure_requires_reload_and_deduplicates(self):
        import ocn_core.checkpoint as checkpoints
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,agent,sink=self.setup(root)
            original=checkpoints.save_checkpoint;calls=[]
            def fail_second(*args):
                calls.append(1)
                if len(calls)==2:raise OSError('after acceptance')
                return original(*args)
            with patch('ocn_core.checkpoint.save_checkpoint',side_effect=fail_second):
                with self.assertRaises(OSError):agent.maintain(32,DissipativeHabitat(h,agent.dna,sink),root/'state')
            with self.assertRaises(ValueError):agent.maintain(33,DissipativeHabitat(h,agent.dna,sink),root/'state')
            agent=load_checkpoint(root/'state',agent.dna,'reactive')
            result=agent.maintain(33,DissipativeHabitat(h,agent.dna,sink),root/'state')
            self.assertTrue(result['maintenance_complete']);self.assertEqual(sink.status()['load'],1)
            self.assertEqual(result['dissipation']['accepted_events'],1)

    def test_cli_maintenance_existing_state_without_readable_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            descriptor=dict(codec='integer',value_path=['amount'])
            (h/'schemas.json').write_text(json.dumps({'s':descriptor}))
            (h/'data.json').write_text(json.dumps(dict(source='s',step=0,amount=47,
                schema_digest=descriptor_digest(descriptor))))
            command=[sys.executable,'-c','from ocn_core.cli import main; raise SystemExit(main())',str(h),
                '--source','s=data.json','--budget','4','--state',str(root/'state'),'--scheduler','paced32',
                '--reservoir',str(root/'sink'),'--repack-refused','--require-schema-binding']
            completed=subprocess.run(command+['--maintenance-only','--step','32'],capture_output=True,text=True)
            self.assertEqual(completed.returncode,2);self.assertFalse((root/'sink').exists())
            subprocess.run(command+['--step','0'],check=True,capture_output=True,text=True)
            for file in h.iterdir():file.unlink()
            completed=subprocess.run(command+['--maintenance-only','--step','32'],check=True,capture_output=True,text=True)
            result=json.loads(completed.stdout)
            self.assertEqual(result['kind'],'maintenance');self.assertTrue(result['maintenance_complete'])
            self.assertEqual([c['operation'] for c in result['calls']],['dissipate'])

if __name__=='__main__':unittest.main()
