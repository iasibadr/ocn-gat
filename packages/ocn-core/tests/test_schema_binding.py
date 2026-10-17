import unittest
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from ocn_core.controller import Agent, DNA, Fault, descriptor_digest, parse


class SchemaBindingTests(unittest.TestCase):
    def test_strict_cli_resume_removal_and_dna_downgrade(self):
        for dissipative in (False, True):
            with self.subTest(dissipative=dissipative), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); habitat=root/'h'; habitat.mkdir()
                descriptor=dict(codec='integer',value_path=['value'])
                (habitat/'schemas.json').write_text(json.dumps({'s':descriptor}))
                (habitat/'directory.json').write_text(json.dumps({'s':'data.json'}))
                command=[sys.executable,'-c','from ocn_core.cli import main; raise SystemExit(main())',
                         str(habitat),'--source','s=data.json','--state',str(root/'state'),
                         '--budget','4','--require-schema-binding']
                if dissipative:
                    command+=['--scheduler','paced32','--repack-refused','--reservoir',str(root/'sink')]
                for step, bound in ((0,True),(1,False),(2,True)):
                    doc=dict(source='s',step=step,value=47)
                    if bound:doc['schema_digest']=descriptor_digest(descriptor)
                    (habitat/'data.json').write_text(json.dumps(doc))
                    completed=subprocess.run(command+['--step',str(step)],capture_output=True,text=True)
                    self.assertEqual(completed.returncode,0 if bound else 2,completed.stderr)
                    result=json.loads(completed.stdout)
                    if bound:self.assertEqual(result['output']['sum'],47)
                    else:
                        self.assertIsNone(result['output'])
                        self.assertEqual(result['errors'],[dict(source='s',code='missing_schema_binding')])
                before=(root/'state').read_bytes()
                downgraded=[arg for arg in command if arg!='--require-schema-binding']
                completed=subprocess.run(downgraded+['--step','3'],capture_output=True,text=True)
                self.assertEqual(completed.returncode,2)
                self.assertIn('DNA mismatch',completed.stderr)
                self.assertEqual((root/'state').read_bytes(),before)

    def test_strict_dna_rejects_coercion(self):
        for value in (1,0,'true',None):
            with self.assertRaises(ValueError):DNA(require_schema_binding=value)

    def test_inconsistent_metadata_and_exhausted_budget_never_release_value(self):
        from ocn_core import DirectoryHabitat
        for budget, expected in ((1,'budget'),(2,'schema')):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                old=dict(codec='integer',value_path=['value'])
                new=dict(codec='integer',value_path=['amount'])
                (root/'schemas.json').write_text(json.dumps({'s':old}))
                (root/'data.json').write_text(json.dumps(dict(source='s',step=0,value=11,
                    amount=47,schema_digest=descriptor_digest(new))))
                dna=DNA(source_ids=('s',),max_cache=1,max_calls=budget,require_schema_binding=True)
                result=Agent('reactive',{'s':'data.json'},dna).step(0,DirectoryHabitat(root,dna))
                self.assertIsNone(result['output'])
                self.assertEqual(result['errors'],[dict(source='s',code=expected)])
                self.assertEqual(result['cost'],budget)

    def test_refresh_then_reuse_without_metadata_call(self):
        dna = DNA(source_ids=('s',), max_cache=1, max_calls=3)
        agent = Agent('reactive', {'s':'data.json'}, dna)
        descriptor = dict(codec='integer', value_path=['amount'])
        class Tools:
            def __init__(self, step):
                self.dna=dna; self.calls=[]; self.cost=0; self.step=step
            def read(self, path):
                self.calls.append('read'); self.cost+=1
                return dict(source='s', step=self.step, value=11, amount=47,
                            schema_digest=descriptor_digest(descriptor))
            def describe(self, source):
                self.calls.append('describe'); self.cost+=1
                return descriptor.copy()
        first=agent.step(0, Tools(0))
        self.assertEqual(first['output']['sum'],47)
        self.assertEqual(first['calls'],['read','describe'])
        second=agent.step(1, Tools(1))
        self.assertEqual(second['output']['sum'],47)
        self.assertEqual(second['calls'],['read'])

    def test_binding_mismatch_and_malformed_are_not_accepted(self):
        descriptor=dict(codec='integer',value_path=['value'])
        for digest, code in [('0'*64,'schema'), (None,'invalid_schema_binding'),
                             ('A'*64,'invalid_schema_binding')]:
            with self.assertRaises(Fault) as caught:
                parse(dict(source='s',step=0,value=11,schema_digest=digest),'s',0,descriptor)
            self.assertEqual(caught.exception.code,code)

    def test_binding_does_not_authorize_new_codec(self):
        descriptor=dict(codec='binary_integer',value_path=['value'])
        with self.assertRaises(Fault) as caught:
            parse(dict(source='s',step=0,value='101',schema_digest=descriptor_digest(descriptor)),
                  's',0,descriptor)
        self.assertEqual(caught.exception.code,'unsupported')
