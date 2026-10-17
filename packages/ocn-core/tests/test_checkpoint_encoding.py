"""Byte compatibility with the historical canonical JSON envelope."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import (Agent,DNA,RepackingAgent,RepackingDNA,DirectoryHabitat,
                     ToolSession,save_checkpoint,load_checkpoint)
from ocn_core.checkpoint import canonical,snapshot
from ocn_core.receipt import FORMAT

# Test the archived research candidate without replacing the production writer.
_candidate_path=Path(__file__).resolve().parents[1]/'benchmarks/checkpoint_encoding_v1/candidate_checkpoint.py'
_spec=importlib.util.spec_from_file_location('ocn_core._encoding_candidate',_candidate_path)
_candidate=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_candidate)
save_checkpoint=_candidate.save_checkpoint


def previous_encoding(agent):
    payload=json.loads(canonical(snapshot(agent)))
    receipt=getattr(agent,'_task_receipt',None)
    unsigned=payload if receipt is None else dict(format=FORMAT,payload=payload,receipt=receipt)
    digest=hashlib.sha256(canonical(unsigned)).hexdigest()
    return canonical(dict(payload=payload,sha256=digest) if receipt is None else dict(unsigned,sha256=digest))


class CheckpointEncodingTests(unittest.TestCase):
    def test_legacy_bytes_unicode_floats_and_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ('classical','ocn'):
                for value in (-0.0,0.1,1e-100,1.0):
                    with self.subTest(kind=kind,value=value):
                        options=dict(source_ids=('é"\\',),max_cache=1)
                        dna=DNA(**options) if kind=='classical' else RepackingDNA(**options,scheduler='paced32',aggregation='eager',emission_phase='after')
                        a=(Agent if kind=='classical' else RepackingAgent)('reactive',{'é"\\':'initial.json'},dna)
                        a.temperature=value
                        a.descriptors['é"\\']['value_path']=['é"\\\n']
                        if kind=='ocn':a.replace_memory('paths','é"\\','new.json',0)
                        expected=previous_encoding(a);path=Path(tmp)/'state'
                        save_checkpoint(a,path)
                        self.assertEqual(path.read_bytes(),expected)
                        self.assertEqual(previous_encoding(load_checkpoint(path,dna,'reactive')),expected)

    def test_receipt_bytes_and_invalid_state_cannot_replace_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            dna=DNA(source_ids=('s',),max_cache=1)
            a=Agent('reactive',{'s':'value.json'},dna)
            (h/'value.json').write_text(json.dumps(dict(source='s',step=0,value=47)))
            session=ToolSession(a,DirectoryHabitat(h,dna),0,request_id='a'*32)
            session.execute(dict(op='read',path='value.json',value=0))
            session.execute(dict(op='finish',path='',value=47))
            session.persist(root/'state');expected=previous_encoding(a)
            save_checkpoint(a,root/'state')
            self.assertEqual((root/'state').read_bytes(),expected)
            for value in (float('nan'),float('inf'),-1):
                a.temperature=value
                with self.assertRaises(ValueError):save_checkpoint(a,root/'state')
                self.assertEqual((root/'state').read_bytes(),expected)


if __name__=='__main__':unittest.main()
