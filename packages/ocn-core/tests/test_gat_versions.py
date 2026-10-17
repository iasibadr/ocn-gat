import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from ocn_core import gat
from ocn_core.application import locked


class GATVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.habitat=self.root/'docs';self.habitat.mkdir()
        self.instance=self.root/'agent'
        self.old='Delivery Friday.';self.new='Delivery Monday.'
        (self.habitat/'old.md').write_text(self.old)
        gat.create(self.instance,self.habitat,{'delivery':'old.md'},'When?')
        self.before=gat.status(self.instance)
        self.old_digest=hashlib.sha256(self.old.encode()).hexdigest()
        self.new_digest=hashlib.sha256(self.new.encode()).hexdigest()

    def update(self,**kwargs):
        return gat.update_document(self.instance,'delivery','new.md',
            kwargs.get('current',self.old_digest),kwargs.get('new',self.new_digest))

    def test_update_keeps_mission_and_pause(self):
        (self.habitat/'new.md').write_text(self.new)
        gat.set_paused(self.instance,True)
        result=self.update();self.assertEqual(result['lifecycle'],'paused')
        self.assertEqual(gat.sources(self.instance)['documents'][0]['sha256'],self.new_digest)
        with self.assertRaises(RuntimeError):gat.run(self.instance,synthesizer=Mock())
        gat.set_paused(self.instance,False)
        self.assertEqual(gat.status(self.instance),self.before)
        def synth(question,documents):
            self.assertEqual(documents[0]['text'],self.new)
            return dict(response=dict(answer=self.new,abstain=False,citations=[dict(document_id='delivery',quote=self.new)]),usage={})
        self.assertEqual(gat.run(self.instance,synthesizer=synth)['citations'][0]['sha256'],self.new_digest)

    def test_wrong_digest_and_stale_update_do_not_mutate(self):
        (self.habitat/'new.md').write_text(self.new)
        state=self.instance/'documents.json';original=state.read_bytes()
        with self.assertRaises(ValueError):self.update(new='0'*64)
        self.assertEqual(state.read_bytes(),original)
        self.update();current=state.read_bytes()
        with self.assertRaisesRegex(ValueError,'conflict'):self.update()
        self.assertEqual(state.read_bytes(),current)

    def test_sources_reports_enrollment_not_freshness(self):
        (self.habitat/'old.md').unlink()
        report=gat.sources(self.instance)
        self.assertFalse(report['fresh_source_check'])
        self.assertEqual(report['documents'][0]['sha256'],self.old_digest)
        with self.assertRaises(ValueError):gat.run(self.instance,synthesizer=Mock())

    def test_unknown_source_and_escape_rejected(self):
        original=(self.instance/'documents.json').read_bytes()
        with self.assertRaises(ValueError):gat.update_document(self.instance,'other','new.md',self.old_digest,self.new_digest)
        with self.assertRaises(ValueError):gat.update_document(self.instance,'delivery','../new.md',self.old_digest,self.new_digest)
        self.assertEqual((self.instance/'documents.json').read_bytes(),original)

    def test_busy_instance_prevents_update(self):
        (self.habitat/'new.md').write_text(self.new)
        with locked(self.instance):
            with self.assertRaises(RuntimeError):self.update()
        self.assertEqual(gat.sources(self.instance)['documents'][0]['sha256'],self.old_digest)

if __name__=='__main__':unittest.main()
