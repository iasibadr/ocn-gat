"""Capture the validated persisted payload without caching mutable agent state."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import Agent,DNA,DirectoryHabitat,ToolSession,save_checkpoint
from ocn_core.checkpoint import canonical,snapshot

_candidate_path=Path(__file__).resolve().parents[1]/'benchmarks/checkpoint_capture_v1/candidate_checkpoint.py'
_spec=importlib.util.spec_from_file_location('ocn_core._capture_candidate',_candidate_path)
_candidate=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_candidate)
save_checkpoint=_candidate.save_checkpoint


class CheckpointCaptureTests(unittest.TestCase):
    def test_optional_return_is_exact_detached_and_default_stays_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state';a=Agent('reactive',{'s':'old'},DNA(source_ids=('s',),max_cache=1))
            self.assertIsNone(save_checkpoint(a,p))
            expected=canonical(snapshot(a));result=save_checkpoint(a,p,True)
            self.assertEqual(result,expected)
            self.assertEqual(json.loads(result),json.loads(p.read_bytes())['payload'])
            a.paths['s']='new'
            self.assertEqual(result,expected)
            for invalid in (1,'yes',None):
                previous=p.read_bytes()
                with self.assertRaises(ValueError):save_checkpoint(a,p,invalid)
                self.assertEqual(p.read_bytes(),previous)

    def test_failure_does_not_return_successful_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state';a=Agent('reactive',{'s':'old'},DNA(source_ids=('s',),max_cache=1))
            save_checkpoint(a,p);previous=p.read_bytes();a.paths['s']='new'
            with patch.object(_candidate.os,'replace',side_effect=OSError('interruption')):
                with self.assertRaises(OSError):save_checkpoint(a,p,True)
            self.assertEqual(p.read_bytes(),previous)

    def test_receipt_document_retained_capture_is_payload_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            (h/'s').write_text(json.dumps(dict(source='s',step=0,value=7)))
            a=Agent('reactive',{'s':'s'},DNA(source_ids=('s',),max_cache=1))
            s=ToolSession(a,DirectoryHabitat(h,a.dna),0,request_id='a'*32)
            s.execute(dict(op='read',path='s',value=0));s.execute(dict(op='finish',path='',value=7))
            s.persist(root/'state');before=(root/'state').read_bytes()
            captured=save_checkpoint(a,root/'state',True)
            self.assertEqual((root/'state').read_bytes(),before)
            self.assertEqual(captured,canonical(snapshot(a)))
            self.assertIn('receipt',json.loads(before));self.assertNotIn('receipt',json.loads(captured))


if __name__=='__main__':unittest.main()
