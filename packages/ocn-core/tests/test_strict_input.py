"""Ambiguous documents must not become verified evidence or recovery metadata."""
import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import Agent,DNA,DirectoryHabitat,ToolSession
from ocn_core.controller import Fault,descriptor_digest,parse

class StrictInputTests(unittest.TestCase):
    def test_duplicate_keys_and_nonfinite_numbers_rejected_at_all_depths(self):
        malformed=[
            '{"source":"wrong","source":"s","step":0,"value":7}',
            '{"source":"s","step":0,"data":{"value":6,"value":7}}',
            r'{"source":"wrong","\u0073ource":"s","step":0,"value":7}',
            '{"source":"s","step":0,"value":7,"extra":NaN}',
            '{"source":"s","step":0,"value":7,"extra":Infinity}',
            '{"source":"s","step":0,"value":7,"extra":-Infinity}',
            '{"source":"s","step":0,"value":7,"extra":1e9999}']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dna=DNA(source_ids=('s',),max_cache=1)
            for raw in malformed:
                with self.subTest(raw=raw):
                    (root/'data.json').write_text(raw)
                    tools=DirectoryHabitat(root,dna)
                    with self.assertRaises(Fault) as raised:tools.read('data.json')
                    self.assertEqual(raised.exception.code,'invalid_document')
                    self.assertEqual(tools.cost,1)
    def test_ambiguous_metadata_never_replaces_memory(self):
        for operation,name,raw in [
            ('locate','directory.json','{"s":"bad.json","s":"good.json"}'),
            ('describe','schemas.json','{"s":{"codec":"integer","value_path":["bad"],"value_path":["value"]}}')]:
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);h=root/'h';h.mkdir();(h/name).write_text(raw)
                dna=DNA(source_ids=('s',),max_cache=1)
                agent=Agent('reactive',{'s':'original.json'},dna)
                before=json.dumps(dict(paths=agent.paths,descriptors=agent.descriptors),sort_keys=True)
                session=ToolSession(agent,DirectoryHabitat(h,dna),0)
                result=session.execute(dict(op=operation,path='',value=0))
                self.assertEqual(result,dict(ok=False,error='invalid_document'))
                self.assertEqual(json.dumps(dict(paths=agent.paths,descriptors=agent.descriptors),sort_keys=True),before)
                self.assertEqual(session.verified,{})
                session.persist(root/'state')
    def test_step_requires_integer_and_bad_reread_revokes_evidence(self):
        descriptor=dict(codec='integer',value_path=['value'])
        for step,expected in ((False,0),(True,1),(0.0,0),(1.0,1)):
            with self.subTest(step=step):
                with self.assertRaises(Fault) as raised:
                    parse(dict(source='s',step=step,value=7), 's',expected,descriptor)
                self.assertEqual(raised.exception.code,'invalid_provenance')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();path=h/'data.json'
            dna=DNA(source_ids=('s',),max_cache=1,require_schema_binding=True)
            session=ToolSession(Agent('reactive',{'s':'data.json'},dna),DirectoryHabitat(h,dna),0)
            doc=dict(source='s',step=0,value=7,schema_digest=descriptor_digest(descriptor))
            path.write_text(json.dumps(doc));self.assertTrue(session.execute(dict(op='read',path='data.json',value=0))['ok'])
            doc['step']=False;path.write_text(json.dumps(doc))
            self.assertEqual(session.execute(dict(op='read',path='data.json',value=0)),dict(ok=False,error='invalid_provenance'))
            self.assertFalse(session.execute(dict(op='finish',path='',value=7))['ok'])
            result=session.persist(root/'state');self.assertFalse(result['done'])

if __name__=='__main__':unittest.main()
