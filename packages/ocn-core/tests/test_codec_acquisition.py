import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from ocn_core import Agent, DNA, CompactAgent, CompactDNA, DirectoryHabitat, save_checkpoint, load_checkpoint
from ocn_core import DissipativeHabitat, CompactReservoir
from ocn_core.controller import Fault, parse

class CodecAcquisitionTests(unittest.TestCase):
    def test_canonical_decimal_and_provenance(self):
        descriptor=dict(codec='decimal_integer',value_path=['payload','amount'])
        for text in ('0','17','-42','9'*128):
            doc=dict(source='s',step=0,payload=dict(amount=text))
            self.assertEqual(parse(doc,'s',0,descriptor,('integer','decimal_integer')),int(text))
            with self.assertRaises(Fault) as error:parse(doc,'s',1,descriptor,('decimal_integer',))
            self.assertEqual(error.exception.code,'invalid_provenance')
        for text in ('01','-0','+1','1.0',' 1','1 ','1e2','١','1\n','9'*129,True,1,None,'__import__("os")'):
            with self.subTest(value=text),self.assertRaises(Fault):
                parse(dict(source='s',step=0,payload=dict(amount=text)),'s',0,descriptor,('decimal_integer',))

    def test_opt_in_and_gate_respect_dna(self):
        doc=dict(source='s',step=0,value='7');desc=dict(codec='decimal_integer',value_path=['value'])
        with self.assertRaises(Fault) as error:parse(doc,'s',0,desc)
        self.assertEqual(error.exception.code,'unsupported')
        for allowed,expected in [(('integer',),[True,False,False,False]),(('integer','decimal_integer'),[True]*4)]:
            dna=CompactDNA(source_ids=('s',),known_unsupported_reactive=True,allowed_codecs=allowed)
            a=CompactAgent('ocn_hamilton',{'s':'s.json'},dna);a.descriptors['s']=desc
            self.assertEqual(a.action_mask('s',np.ones(4,dtype=bool)).tolist(),expected)
        for bad in ((),('eval',),('integer','integer'),['integer']):
            with self.assertRaises(ValueError):DNA(allowed_codecs=bad)

    def test_acquisition_reuse_checkpoint_and_default_refusal(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);h=root/'habitat';h.mkdir()
            dna=DNA(source_ids=('s',),allowed_codecs=('integer','decimal_integer'))
            a=Agent('reactive',{'s':'s.json'},dna)
            (h/'schemas.json').write_text(json.dumps({'s':dict(codec='decimal_integer',value_path=['payload','amount'])}))
            costs=[]
            for n in range(3):
                (h/'s.json').write_text(json.dumps(dict(source='s',step=n,payload=dict(amount='42'))))
                result=a.step(n,DirectoryHabitat(h,dna));costs.append(result['cost'])
                self.assertEqual(result['output']['sum'],42)
                save_checkpoint(a,root/'state');a=load_checkpoint(root/'state',dna,'reactive')
            self.assertEqual(costs,[2,1,1])
            with self.assertRaises(ValueError):load_checkpoint(root/'state',DNA(source_ids=('s',)),'reactive')
            old=DNA(source_ids=('s',));b=Agent('reactive',{'s':'s.json'},old)
            self.assertIsNone(b.step(2,DirectoryHabitat(h,old))['output'])

    def test_compact_acquisition_retires_previous_descriptor_and_resumes(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);h=root/'habitat';h.mkdir()
            dna=CompactDNA(source_ids=('s',),allowed_codecs=('integer','decimal_integer'),
                max_calls=6,emission_phase='after',aggregation='eager',learning_scope='source',
                known_unsupported_reactive=True)
            a=CompactAgent('reactive',{'s':'s.json'},dna)
            sink=CompactReservoir(root/'sink',4)
            (h/'schemas.json').write_text(json.dumps({'s':dict(codec='decimal_integer',value_path=['value'])}))
            for n in range(3):
                (h/'s.json').write_text(json.dumps(dict(source='s',step=n,value='17')))
                tools=DissipativeHabitat(h,dna,sink)
                a.step(n,tools);result=a.finish_request(n,tools,root/'state')
                self.assertEqual(result['output']['sum'],17)
                self.assertLessEqual(result['cost'],6)
                self.assertEqual(a.retirement['retired_events'],1)
                self.assertEqual(a.retirement['accepted_events'],1)
                a=load_checkpoint(root/'state',dna,'reactive')
            self.assertEqual(a.descriptors['s']['codec'],'decimal_integer')

if __name__=='__main__':unittest.main()
