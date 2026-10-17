import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import (Agent,DNA,ToolSession,DirectoryHabitat,RepackingAgent,RepackingDNA,
    DissipativeHabitat,CompactReservoir,load_checkpoint)
from ocn_core.controller import descriptor_digest


def action(op,source='',path='',value=0):return dict(op=op,source=source,path=path,value=value)

class MultiSourceTests(unittest.TestCase):
    def setup(self,root,ocn=False,step=0):
        h=root/'h';h.mkdir()
        options=dict(source_ids=('a','b'),max_cache=2,max_calls=8,require_schema_binding=True)
        dna=RepackingDNA(**options,scheduler='paced32',aggregation='eager',emission_phase='after') if ocn else DNA(**options)
        agent=(RepackingAgent if ocn else Agent)('reactive',{'a':'a.json','b':'b.json'},dna)
        descriptor=dict(codec='integer',value_path=['value'])
        for source,value in (('a',-4),('b',9)):
            (h/(source+'.json')).write_text(json.dumps(dict(source=source,step=step,value=value,
                schema_digest=descriptor_digest(descriptor))))
        (h/'directory.json').write_text(json.dumps({'a':'a.json','b':'b.json'}))
        (h/'schemas.json').write_text(json.dumps({'a':descriptor,'b':descriptor}))
        sink=CompactReservoir(root/'sink',2) if ocn else None
        tools=DissipativeHabitat(h,dna,sink) if ocn else DirectoryHabitat(h,dna)
        return agent,tools

    def test_no_partial_or_cross_source_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup(root);s=ToolSession(agent,tools,0,max_decisions=12)
            self.assertEqual(s.execute(action('read','a','a.json'))['result'],-4)
            self.assertEqual(s.execute(action('finish',value=-4))['error'],'unverified_answer')
            self.assertEqual(s.execute(action('read','b','a.json'))['error'],'invalid_provenance')
            self.assertEqual(s.execute(action('finish',value=-8))['error'],'unverified_answer')
            self.assertEqual(s.execute(action('read','b','b.json'))['result'],9)
            self.assertEqual(s.execute(action('finish',value=5))['value'],5)
            self.assertEqual(s.persist(root/'state')['answer'],5)

    def test_refresh_invalidates_only_target_and_cannot_finish_with_stale_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup(root);s=ToolSession(agent,tools,0,max_decisions=12)
            for source in ('a','b'):s.execute(action('read',source,source+'.json'))
            s.execute(action('describe','b'))
            self.assertEqual(s.execute(action('finish',value=5))['error'],'unverified_answer')
            s.execute(action('read','b','b.json'))
            self.assertTrue(s.execute(action('finish',value=5))['ok'])
            self.assertEqual(len(tools.calls),4)
            s.persist(root/'state')

    def test_error_on_required_source_survives_observation_of_other_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup(root);s=ToolSession(agent,tools,0)
            doc=json.loads((tools.root/'a.json').read_text());doc['step']=999
            (tools.root/'a.json').write_text(json.dumps(doc))
            s.execute(action('read','a','a.json'));s.execute(action('read','b','b.json'))
            self.assertEqual(s.execute(action('abstain'))['error'],'invalid_provenance')
            result=s.persist(root/'state');self.assertTrue(result['refused']);self.assertIsNone(result['answer'])

    def test_unknown_or_unspecified_source_never_calls_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup(root);s=ToolSession(agent,tools,0)
            for source in ('','outsider'):
                self.assertEqual(s.execute(action('read',source,'a.json'))['error'],'denied_source')
            self.assertEqual(s.execute(dict(op='read',path='a.json',value=0))['error'],'denied_source')
            self.assertEqual(tools.calls,[])
            s.persist(root/'state')

    def test_independent_repairs_retirement_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agent,tools=self.setup(root,ocn=True,step=32)
            (tools.root/'a.json').rename(tools.root/'moved.json')
            (tools.root/'directory.json').write_text(json.dumps({'a':'moved.json','b':'b.json'}))
            descriptor=dict(codec='integer',value_path=['amount'])
            (tools.root/'b.json').write_text(json.dumps(dict(source='b',step=32,value=9,amount=20,
                schema_digest=descriptor_digest(descriptor))))
            (tools.root/'schemas.json').write_text(json.dumps({'b':descriptor}))
            s=ToolSession(agent,tools,32,max_decisions=10)
            for op,source,path in [('read','a','a.json'),('locate','a',''),('read','a','moved.json'),
                                   ('read','b','b.json'),('describe','b',''),('read','b','b.json')]:
                s.execute(action(op,source,path))
            self.assertEqual(s.execute(action('finish',value=16))['value'],16)
            result=s.persist(root/'state')
            self.assertEqual(result['cost'],7)
            self.assertEqual(result['dissipation']['accepted_events'],2)
            loaded=load_checkpoint(root/'state',agent.dna,'reactive')
            self.assertEqual(loaded.paths['a'],'moved.json')
            self.assertEqual(loaded.descriptors['b'],descriptor)
            # Persistent memory is reusable, but proofs must be reacquired each request.
            next_session=ToolSession(loaded,DissipativeHabitat(tools.root,loaded.dna,tools.reservoir),33)
            self.assertEqual(next_session.execute(action('finish',value=16))['error'],'unverified_answer')
            next_session.persist(root/'state')

if __name__=='__main__':unittest.main()
