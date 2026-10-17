import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import (Agent,DNA,ToolSession,DirectoryHabitat,save_checkpoint,load_checkpoint,
    RepackingAgent,RepackingDNA,CompactReservoir,DissipativeHabitat)
from ocn_core.controller import descriptor_digest
from ocn_core.checkpoint import snapshot


def action(op,path='',value=0):return dict(op=op,path=path,value=value)

class ToolSessionTests(unittest.TestCase):
    def setup_agent(self,root):
        root=root/'h';root.mkdir()
        dna=DNA(source_ids=('s',),max_cache=1,max_calls=4,require_schema_binding=True)
        descriptor=dict(codec='integer',value_path=['value'])
        (root/'data.json').write_text(json.dumps(dict(source='s',step=0,value=47,
            schema_digest=descriptor_digest(descriptor))))
        agent=Agent('reactive',{'s':'data.json'},dna)
        return agent,DirectoryHabitat(root,dna)

    def test_ownership_closure_and_unverified_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup_agent(root)
            session=ToolSession(agent,tools,0)
            for operation in (lambda:ToolSession(agent,DirectoryHabitat(root,agent.dna),1),
                              lambda:agent.step(1,DirectoryHabitat(root,agent.dna)),lambda:snapshot(agent)):
                with self.assertRaises(ValueError):operation()
            self.assertEqual(session.execute(action('finish',value=47))['error'],'unverified_answer')
            session.execute(action('read','data.json'))
            session.execute(action('finish',value=47))
            with self.assertRaises(ValueError):session.persist(root/'h'/'state')
            result=session.persist(root/'state')
            self.assertEqual(result['answer'],47)
            for operation in (lambda:session.persist(root/'state'),lambda:session.execute(action('read','data.json'))):
                with self.assertRaises(ValueError):operation()
            loaded=load_checkpoint(root/'state',agent.dna,'reactive')
            self.assertEqual(loaded.last_step,0)

    def test_decision_limit_applies_to_invalid_actions_and_can_close_unfinished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup_agent(root)
            session=ToolSession(agent,tools,0,max_decisions=1)
            self.assertEqual(session.execute(None)['error'],'invalid_action')
            self.assertEqual(session.execute(action('read','data.json'))['error'],'decision_budget')
            self.assertEqual(tools.calls,[])
            result=session.persist(root/'state')
            self.assertFalse(result['done']);self.assertIsNone(result['answer'])

    def test_failed_save_requires_reload_and_preserves_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup_agent(root)
            save_checkpoint(agent,root/'state');original=(root/'state').read_bytes()
            session=ToolSession(agent,tools,0)
            with patch('ocn_core.tool_session.save_checkpoint',side_effect=OSError('injected')):
                with self.assertRaises(OSError):session.persist(root/'state')
            self.assertEqual((root/'state').read_bytes(),original)
            for operation in (lambda:ToolSession(agent,DirectoryHabitat(root,agent.dna),1),
                              lambda:agent.step(1,DirectoryHabitat(root,agent.dna)),lambda:snapshot(agent)):
                with self.assertRaises(ValueError):operation()
            loaded=load_checkpoint(root/'state',agent.dna,'reactive')
            recovered=ToolSession(loaded,DirectoryHabitat(root/'h',loaded.dna),0)
            recovered.execute(action('read','data.json'));recovered.execute(action('finish',value=47))
            self.assertEqual(recovered.persist(root/'state')['answer'],47)

    def test_replay_real_llm_actions_through_public_interface(self):
        trace=Path(__file__).resolve().parents[1]/'benchmarks/llm_planner_pair_v1/results.json'
        rows=json.loads(trace.read_text())['rows']
        for arm in ('classical','ocn'):
            with self.subTest(arm=arm),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);h=root/'h';h.mkdir()
                options=dict(source_ids=('s',),max_cache=1,max_calls=4,require_schema_binding=True)
                dna=DNA(**options) if arm=='classical' else RepackingDNA(**options,scheduler='paced32',aggregation='eager',emission_phase='after')
                agent=(Agent if arm=='classical' else RepackingAgent)('reactive',{'s':'initial.json'},dna)
                sink=CompactReservoir(root/'sink',2)
                for row in (r for r in rows if r['arm']==arm):
                    index=row['case'];step=row['step'];value=row['expected']
                    if index:agent=load_checkpoint(root/'state',dna,'reactive')
                    path='initial.json' if index==0 else 'moved.json'
                    if index==1:(h/'initial.json').unlink()
                    field='value' if index<2 else 'amount'
                    descriptor=dict(codec='binary_integer' if value is None else 'integer',value_path=[field])
                    doc=dict(source='s',step=step,value=11,schema_digest=descriptor_digest(descriptor))
                    doc[field]='101' if value is None else value
                    for name,data in ((path,doc),('directory.json',{'s':path}),('schemas.json',{'s':descriptor})):
                        (h/name).write_text(json.dumps(data))
                    tools=DirectoryHabitat(h,dna) if arm=='classical' else DissipativeHabitat(h,dna,sink)
                    session=ToolSession(agent,tools,step)
                    for turn in row['turns']:
                        self.assertEqual(session.execute(turn['action']),turn['feedback'])
                    result=session.persist(root/'state')
                    self.assertEqual(result['answer'],row['result']['answer'])
                    self.assertEqual(result['refused'],row['result']['refused'])
                    self.assertEqual(result['cost'],row['result']['cost'])
                    if arm=='ocn':
                        for key in ('retired_events','accepted_events','merges'):
                            self.assertEqual(agent.retirement[key],row['retirement'][key])

    def test_accepted_retirement_then_save_failure_replays_without_double_count(self):
        import ocn_core.checkpoint as checkpoints
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            dna=RepackingDNA(source_ids=('s',),max_cache=1,max_calls=4,require_schema_binding=True,
                scheduler='paced32',aggregation='eager',emission_phase='after')
            agent=RepackingAgent('reactive',{'s':'old.json'},dna)
            sink=CompactReservoir(root/'sink',2)
            descriptor=dict(codec='integer',value_path=['value'])
            (h/'directory.json').write_text(json.dumps({'s':'new.json'}))
            def document(step):
                (h/'new.json').write_text(json.dumps(dict(source='s',step=step,value=47,
                    schema_digest=descriptor_digest(descriptor))))
            document(32)
            session=ToolSession(agent,DissipativeHabitat(h,dna,sink),32)
            session.execute(action('locate'));session.execute(action('read','new.json'))
            session.execute(action('finish',value=47))
            original=checkpoints.save_checkpoint;calls=[]
            def save_or_fail(*args):
                calls.append(1)
                if len(calls)==2:raise OSError('after sink acceptance')
                return original(*args)
            with patch('ocn_core.checkpoint.save_checkpoint',side_effect=save_or_fail):
                with self.assertRaises(OSError):session.persist(root/'state')
            self.assertEqual(len(calls),2)
            with self.assertRaises(ValueError):ToolSession(agent,DissipativeHabitat(h,dna,sink),33)
            loaded=load_checkpoint(root/'state',dna,'reactive')
            self.assertEqual(loaded.retirement['accepted_events'],0)
            self.assertTrue(loaded.retirement['pending'][0]['sealed'])
            document(33)
            resumed=ToolSession(loaded,DissipativeHabitat(h,dna,sink),33)
            resumed.execute(action('read','new.json'));resumed.execute(action('finish',value=47))
            result=resumed.persist(root/'state')
            self.assertEqual(result['dissipation']['accepted_events'],1)
            self.assertEqual(result['dissipation']['pending'],0)
            self.assertEqual(result['dissipation']['pressure'],0.5)
            self.assertEqual(sink.status()['load'],1)

if __name__=='__main__':unittest.main()
