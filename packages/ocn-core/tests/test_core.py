from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from ocn_core import Agent, DNA, DirectoryHabitat, Fault

class CoreTests(unittest.TestCase):
    def test_sealed_au2_controller_parity(self):
        path = Path(__file__).resolve().parents[3] / 'experiments/ocn_autonomy_policy/model.py'
        spec = importlib.util.spec_from_file_location('sealed_au2', path)
        old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = old
        spec.loader.exec_module(old)
        class TranslatedTools:
            def __init__(self, tools): self.tools = tools
            def __getattr__(self, name):
                value = getattr(self.tools, name)
                if name not in ('read', 'locate', 'describe'): return value
                def call(*args):
                    try: return value(*args)
                    except old.Fault as exc: raise Fault(exc.code) from None
                return call
        for policy in old.POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as root:
                world = old.World(root, 220088, 'burst'); world.prepare(0)
                a = old.Agent(policy, world.paths, seed=220088)
                b = Agent(policy, world.paths, seed=220088)
                for n in range(96):
                    world.prepare(n)
                    before=a.step(n, old.Tools(world, a.dna))
                    after=b.step(n, TranslatedTools(old.Tools(world, b.dna)))
                    # Codec permissions enlarge DNA; validate each identity independently.
                    for result,agent in ((before,a),(after,b)):
                        expected=hashlib.sha256(json.dumps(asdict(agent.dna),sort_keys=True).encode()).hexdigest()
                        self.assertEqual(result.pop('identity'),expected)
                    self.assertEqual(before,after)

    def test_real_files_repair_and_second_request_memory(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            (p/'directory.json').write_text(json.dumps({'one':'new.json'}))
            (p/'schemas.json').write_text(json.dumps({'one':{'codec':'integer','value_path':['data','measure']}}))
            def write(n):
                (p/'new.json').write_text(json.dumps({'source':'one','step':n,'data':{'measure':42}}))
            dna = DNA(max_calls=4, max_cache=1, source_ids=('one',))
            agent = Agent('reactive', {'one':'old.json'}, dna)
            write(0); first = agent.step(0, DirectoryHabitat(root,dna))
            self.assertEqual(first['output']['sum'], 42);self.assertEqual(first['cost'],4)
            write(1); second = agent.step(1, DirectoryHabitat(root,dna))
            self.assertEqual(second['output']['sum'],42);self.assertEqual(second['cost'],1)

    def test_budget_fault_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            dna=DNA(max_calls=1,max_cache=1,source_ids=('one',))
            r=Agent('reactive',{'one':'missing.json'},dna).step(0,DirectoryHabitat(root,dna))
            self.assertIsNone(r['output']);self.assertEqual(r['cost'],1)
            self.assertEqual(r['errors'][0]['code'],'budget')

    def test_request_contract(self):
        with tempfile.TemporaryDirectory() as root:
            dna=DNA(max_calls=1,max_cache=1,source_ids=('one',))
            agent=Agent('reactive',{'one':'missing.json'},dna)
            with self.assertRaises(ValueError):agent.step(-1,DirectoryHabitat(root,dna))
            with self.assertRaises(ValueError):agent.step(0,DirectoryHabitat(root,DNA()))
            agent.step(0,DirectoryHabitat(root,dna))
            with self.assertRaises(ValueError):agent.step(0,DirectoryHabitat(root,dna))

    def test_input_membrane(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);dna=DNA();h=DirectoryHabitat(root,dna,max_document_bytes=32)
            (p/'large.json').write_text(' '*33)
            (p/'bad.json').write_text('[]')
            (p/'link.json').symlink_to(p/'bad.json')
            for name,code in [('large.json','document_too_large'),('bad.json','invalid_document'),('link.json','denied'),('../outside','denied'),('schemas.json','denied')]:
                with self.assertRaises(Fault) as e:h.read(name)
                self.assertEqual(e.exception.code,code)
            self.assertEqual(h.cost,5)

    def test_identity_and_configuration(self):
        with self.assertRaises(ValueError):DNA(source_ids=('a','a'))
        with self.assertRaises(ValueError):DNA(max_calls=2)
        with self.assertRaises(ValueError):Agent('made_up',{'alpha':'a','beta':'b','gamma':'c'})
        with self.assertRaises(ValueError):Agent('reactive',{})
        dna=DNA()
        with self.assertRaises(AttributeError):dna.max_calls=100

    def test_unknown_codec_and_bad_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);dna=DNA(max_calls=3,max_cache=1,source_ids=('one',))
            (p/'schemas.json').write_text(json.dumps({'one':{'codec':'unknown','value_path':['value']}}))
            (p/'data.json').write_text(json.dumps({'source':'one','step':0,'value':'encoded'}))
            r=Agent('reactive',{'one':'data.json'},dna).step(0,DirectoryHabitat(root,dna))
            self.assertIsNone(r['output']);self.assertEqual(r['errors'][0]['code'],'unsupported')
            (p/'data.json').write_text(json.dumps({'source':'other','step':0,'value':4}))
            r=Agent('reactive',{'one':'data.json'},dna).step(0,DirectoryHabitat(root,dna))
            self.assertEqual(r['errors'][0]['code'],'invalid_provenance')

if __name__ == '__main__':unittest.main()
