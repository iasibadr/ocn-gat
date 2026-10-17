"""Admission checks with actual filesystem reads and durable checkpoints."""
import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import Agent, DNA, ToolSession, DirectoryHabitat, load_checkpoint
from ocn_core.controller import descriptor_digest


def act(op, path='', source='s'):
    return dict(op=op,path=path,value=0,source=source)


class MetadataAdmissionTests(unittest.TestCase):
    def fixture(self, root):
        h=root/'habitat'; h.mkdir()
        dna=DNA(source_ids=('s','b'),max_cache=2,max_calls=12,require_schema_binding=True)
        agent=Agent('reactive',{'s':'old.json','b':'b.json'},dna)
        return h,agent

    def write(self,h,name,value):
        (h/name).write_text(json.dumps(value))

    def document(self,h,name,descriptor,source='s'):
        self.write(h,name,dict(source=source,step=0,value=7,amount=9,
                              schema_digest=descriptor_digest(descriptor)))

    def test_verified_read_promotes_both_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            d=dict(codec='integer',value_path=['amount'])
            self.write(h,'directory.json',{'s':'new.json'})
            self.write(h,'schemas.json',{'s':d});self.document(h,'new.json',d)
            s=ToolSession(a,DirectoryHabitat(h,a.dna),0,stage_metadata=True)
            s.execute(act('locate')); feedback=s.execute(act('describe'))
            feedback['result']['value_path'][0]='corrupted_by_caller'
            self.assertEqual(a.paths['s'],'old.json')
            self.assertEqual(a.descriptors['s']['value_path'],['value'])
            self.assertEqual(s.execute(act('read','new.json')),dict(ok=True,result=9))
            self.assertEqual(a.paths['s'],'new.json');self.assertEqual(a.descriptors['s'],d)
            self.assertEqual(a.paths['b'],'b.json')
            s.persist(root/'state')
            loaded=load_checkpoint(root/'state',a.dna,'reactive')
            self.assertEqual(loaded.paths['s'],'new.json');self.assertEqual(loaded.descriptors['s'],d)

    def test_failed_read_and_unfinished_session_do_not_poison_checkpoint(self):
        for failure in ('missing','wrong_source','wrong_binding','unsupported'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);h,a=self.fixture(root)
                old=a.descriptors['s'].copy()
                d=dict(codec='binary_integer' if failure=='unsupported' else 'integer',value_path=['amount'])
                self.write(h,'directory.json',{'s':'new.json'});self.write(h,'schemas.json',{'s':d})
                if failure!='missing':
                    self.document(h,'new.json',old if failure=='wrong_binding' else d,
                                  source='b' if failure=='wrong_source' else 's')
                s=ToolSession(a,DirectoryHabitat(h,a.dna),0,stage_metadata=True)
                s.execute(act('locate'));s.execute(act('describe'))
                self.assertFalse(s.execute(act('read','new.json'))['ok'])
                self.assertEqual(s.verified,{})
                s.persist(root/'state')
                loaded=load_checkpoint(root/'state',a.dna,'reactive')
                self.assertEqual(loaded.paths['s'],'old.json');self.assertEqual(loaded.descriptors['s'],old)
                self.assertEqual(s._candidate_paths,{});self.assertEqual(s._candidate_descriptors,{})

    def test_unrelated_success_does_not_promote_unread_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            self.write(h,'directory.json',{'s':'missing.json'})
            self.document(h,'old.json',a.descriptors['s'])
            s=ToolSession(a,DirectoryHabitat(h,a.dna),0,stage_metadata=True)
            s.execute(act('locate'));self.assertTrue(s.execute(act('read','old.json'))['ok'])
            self.assertEqual(a.paths['s'],'old.json')
            s.persist(root/'state')

    def test_latest_candidate_replaces_previous_with_bounded_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            s=ToolSession(a,DirectoryHabitat(h,a.dna),0,stage_metadata=True)
            for path in ('first.json','second.json','third.json'):
                self.write(h,'directory.json',{'s':path});s.execute(act('locate'))
                self.assertEqual(s._candidate_paths,{'s':path})
            self.document(h,'third.json',a.descriptors['s'])
            self.assertTrue(s.execute(act('read','third.json'))['ok'])
            self.assertEqual(a.paths['s'],'third.json');self.assertEqual(s._candidate_paths,{})
            s.persist(root/'state')

    def test_staging_requires_explicit_boolean_and_bound_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            for value in (1,'yes',None):
                with self.assertRaises(ValueError):
                    ToolSession(a,DirectoryHabitat(h,a.dna),0,stage_metadata=value)
            dna=DNA(source_ids=('s',),max_cache=1)
            a=Agent('reactive',{'s':'old.json'},dna)
            with self.assertRaises(ValueError):
                ToolSession(a,DirectoryHabitat(h,dna),0,stage_metadata=True)
            self.assertEqual(a.last_step,-1)


if __name__=='__main__':unittest.main()
