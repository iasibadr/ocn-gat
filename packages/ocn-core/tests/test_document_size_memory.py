import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core.document_adapter import DocumentAdapter
from ocn_core import gat


class DocumentSizeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.habitat=self.root/'h';self.habitat.mkdir()
        self.text='Livraison prévue vendredi.';self.size=len(self.text.encode('utf-8'))
        (self.habitat/'source.md').write_text(self.text,encoding='utf-8')
        self.adapter=DocumentAdapter(self.habitat,self.root/'state.json')
        self.document=self.adapter.bind('plan','source.md')

    def legacy(self):
        data=json.loads(self.adapter.state.read_text());data['format']='ocn.documents.v1'
        for binding in data['documents'].values():binding.pop('byte_length',None)
        self.adapter.state.write_text(json.dumps(data))

    def move(self):
        (self.habitat/'source.md').rename(self.habitat/'moved.md')
        (self.habitat/'decoy.md').write_text('x'*70000)

    def test_persisted_utf8_length_enables_first_read_after_restart(self):
        self.move();restored=DocumentAdapter(self.habitat,self.adapter.state)
        document=restored.read('plan')
        self.assertEqual(document.path,'moved.md');self.assertEqual(document.bytes_read,2*self.size)
        self.assertEqual(restored.bindings()['plan']['byte_length'],self.size)
        self.assertEqual(DocumentAdapter(self.habitat,self.adapter.state).read('plan').entries_scanned,0)

    def test_legacy_only_upgrades_after_verified_read(self):
        self.legacy();before=self.adapter.state.read_bytes()
        self.adapter.bindings();self.assertEqual(self.adapter.state.read_bytes(),before)
        self.adapter.read('plan')
        data=json.loads(self.adapter.state.read_text());self.assertEqual(data['format'],'ocn.documents.v2')
        self.assertEqual(data['documents']['plan']['byte_length'],self.size)
        self.move();self.assertEqual(self.adapter.read('plan').path,'moved.md')

    def test_unobserved_legacy_length_is_not_invented_or_promoted(self):
        self.legacy();before=self.adapter.state.read_bytes();self.move()
        with self.assertRaisesRegex(ValueError,'budget exceeded'):self.adapter.read('plan')
        self.assertEqual(self.adapter.state.read_bytes(),before)

    def test_authorized_version_update_replaces_size_and_identity_together(self):
        text='Monday.';path=self.habitat/'new.md';path.write_text(text)
        digest=hashlib.sha256(text.encode()).hexdigest()
        self.adapter.accept_version('plan','new.md',expected_current_sha256=self.document.sha256,expected_new_sha256=digest)
        path.rename(self.habitat/'moved.md');(self.habitat/'decoy.md').write_text('x'*70000)
        result=DocumentAdapter(self.habitat,self.adapter.state).read('plan')
        self.assertEqual(result.text,text);self.assertEqual(result.bytes_read,2*len(text))
        self.assertEqual(self.adapter.bindings()['plan']['byte_length'],len(text))

    def test_invalid_size_and_failed_atomic_write_do_not_promote(self):
        original=self.adapter.state.read_bytes()
        for size in (True,-1,1.5,'27'):
            data=json.loads(original);data['documents']['plan']['byte_length']=size
            self.adapter.state.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'byte length'):self.adapter.bindings()
        self.adapter.state.write_bytes(original);self.move()
        with patch('ocn_core.document_adapter.os.replace',side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):self.adapter.read('plan')
        self.assertEqual(self.adapter.state.read_bytes(),original)

    def test_missing_state_destination_is_not_misread_as_missing_document(self):
        self.legacy();before=self.adapter.state.read_bytes()
        with patch.object(self.adapter,'_save',side_effect=FileNotFoundError('state unavailable')):
            with patch.object(self.adapter,'_read',wraps=self.adapter._read) as read:
                with self.assertRaises(FileNotFoundError):self.adapter.read('plan')
                self.assertEqual(read.call_count,1)
        self.assertEqual(self.adapter.state.read_bytes(),before)

    def test_gat_first_request_after_move_reuses_enrollment_observation(self):
        instance=self.root/'agent'
        gat.create(instance,self.habitat,{'plan':'source.md'},'Quand?')
        self.move()
        def synth(question,documents):
            return dict(response=dict(answer='vendredi',abstain=False,citations=[dict(document_id='plan',quote='vendredi')]),usage={})
        result=gat.run(instance,synthesizer=synth)
        self.assertEqual(result['citations'][0]['path'],'moved.md')
        self.assertEqual(result['document_bytes_read'],3*self.size)
        self.assertEqual(gat.run(instance,synthesizer=synth)['discovery_entries'],0)


if __name__=='__main__':unittest.main()
