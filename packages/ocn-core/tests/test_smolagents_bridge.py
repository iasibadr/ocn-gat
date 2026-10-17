"""Optional real-framework replay; no live inference or network access."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from ocn_core import (Agent,DNA,RepackingAgent,RepackingDNA,ToolSession,TaskSpec,
                      DirectoryHabitat,DissipativeHabitat,CompactReservoir,load_checkpoint)
from ocn_core.controller import descriptor_digest
try:
    from ocn_core.integrations.smolagents import run_session,LocalModel
    AVAILABLE=True
except ModuleNotFoundError as exc:
    if exc.name not in ('smolagents','yaml'):raise
    AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'Install ocn-core[smolagents] for framework replay')
class FrameworkReplayTests(unittest.TestCase):
    def test_all_recorded_requests_actions_results_and_restores_match(self):
        reference=Path(__file__).resolve().parents[1]/'benchmarks/smolagents_refusal_v2/results.json'
        records=json.loads(reference.read_text())['rows']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agents={}
            for arm in ('classical','ocn'):
                p=root/arm;p.mkdir();(p/'h').mkdir()
                opts=dict(source_ids=('a','b'),max_cache=2,max_calls=8,require_schema_binding=True)
                dna=DNA(**opts) if arm=='classical' else RepackingDNA(**opts,scheduler='paced32',aggregation='eager',emission_phase='after')
                agents[arm]=(Agent if arm=='classical' else RepackingAgent)('reactive',{'a':'a.json','b':'b.json'},dna)
            sink=CompactReservoir(root/'sink',2)
            for record in records:
                arm=record['arm'];step=record['step'];p=root/arm;h=p/'h';agent=agents[arm]
                if step:
                    agent=load_checkpoint(p/'state',agent.dna,'reactive');agents[arm]=agent
                a,b={0:(3,8),1:(3,8),32:(-6,15),64:(-12,-2)}[step]
                paths=dict(a='a.json' if step==0 else 'moved.json',b='b.json')
                if step==1:(h/'a.json').unlink()
                descriptors={}
                for source,value in [('a',a),('b',b)]:
                    descriptor=dict(codec='binary_integer' if source=='b' and step==1 else 'integer',
                                    value_path=['amount'] if source=='b' and step else ['value'])
                    descriptors[source]=descriptor
                    doc=dict(source=source,step=step,value=9999)
                    doc[descriptor['value_path'][0]]='1000' if descriptor['codec']=='binary_integer' else value
                    doc['schema_digest']=descriptor_digest(descriptor)
                    (h/paths[source]).write_text(json.dumps(doc))
                (h/'directory.json').write_text(json.dumps(paths));(h/'schemas.json').write_text(json.dumps(descriptors))
                tools=DirectoryHabitat(h,agent.dna) if arm=='classical' else DissipativeHabitat(h,agent.dna,sink)
                task=record['result']['task']
                session=ToolSession(agent,tools,step,max_decisions=14,task=TaskSpec(task['operation'],tuple(task['sources'])))
                expected=iter(record['trace']['model_trace']);count=0
                def replay(route,payload,timeout):
                    nonlocal count
                    call=next(expected);count+=1
                    self.assertEqual(route,'chat');self.assertGreater(timeout,0)
                    self.assertEqual(payload,call['request'])
                    return copy.deepcopy(call['response'])
                trace=run_session(session,time.monotonic()+30,request=replay)
                self.assertEqual(count,len(record['trace']['model_trace']))
                self.assertEqual(trace,record['trace'])
                self.assertEqual(json.loads(json.dumps(session.persist(p/'state'))),record['result'])
                self.assertEqual(tools.calls,record['tools'])

    def test_task_subset_hides_unrelated_memory_and_rejects_cross_source_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            dna=DNA(source_ids=('a','b'),max_cache=2,max_calls=8,require_schema_binding=True)
            agent=Agent('reactive',{'a':'a.json','b':'unrelated_private_path.json'},dna)
            agent.descriptors['b']=dict(codec='integer',value_path=['unrelated_private_field'])
            descriptor=agent.descriptors['a']
            (h/'a.json').write_text(json.dumps(dict(source='a',step=0,value=5,schema_digest=descriptor_digest(descriptor))))
            tools=DirectoryHabitat(h,dna)
            session=ToolSession(agent,tools,0,max_decisions=8,task=TaskSpec('sum',('a',)))
            scripted=iter([
                dict(name='read',source='b',path='b.json',answer=0),
                dict(name='read',source='a',path='a.json',answer=0),
                dict(name='final_answer',source='',path='',answer=999),
                dict(name='evaluate',source='',path='',answer=0),
                dict(name='final_answer',source='',path='',answer=5)])
            requests=[]
            def provider(route,payload,timeout):
                requests.append(copy.deepcopy(payload))
                return dict(message=dict(role='assistant',content=json.dumps(next(scripted))))
            trace=run_session(session,time.monotonic()+30,request=provider)
            result=session.persist(root/'state')
            self.assertIsNone(trace['error'])
            self.assertTrue(result['done']);self.assertFalse(result['refused']);self.assertEqual(result['answer'],5)
            self.assertEqual(len(requests),5)
            self.assertFalse(trace['actions'][0]['feedback']['ok'])
            self.assertFalse(trace['actions'][2]['feedback']['ok'])
            self.assertEqual([c['operation'] for c in tools.calls],['read','evaluate'])
            wire=json.dumps(requests)
            self.assertNotIn('unrelated_private_path',wire)
            self.assertNotIn('unrelated_private_field',wire)
            self.assertEqual(agent.paths['b'],'unrelated_private_path.json')

    def test_invalid_deadline_and_closed_session_do_not_call_provider(self):
        calls=[]
        for deadline in (0,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):LocalModel(deadline,request=lambda *a,**k:calls.append(a))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();dna=DNA(source_ids=('a',),max_cache=1)
            session=ToolSession(Agent('reactive',{'a':'a'},dna),DirectoryHabitat(h,dna),0)
            session.persist(root/'state')
            with self.assertRaises(ValueError):run_session(session,time.monotonic()+30,request=lambda *a,**k:calls.append(a))
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
