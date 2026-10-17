import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from ocn_core import gat
from ocn_core.application import locked


class GATTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.habitat = self.root/'habitat'; self.habitat.mkdir()
        (self.habitat/'a.md').write_text('Delivery is Friday.')
        self.instance = self.root/'agent'

    def create(self):
        return gat.create(self.instance, self.habitat, {'schedule':'a.md'}, 'When is delivery?')

    def synth(self, question, documents):
        return dict(response=dict(answer='Friday.', abstain=False,
            citations=[dict(document_id='schedule',quote='Delivery is Friday.')]),usage={})

    def test_restart_relocation_and_pause(self):
        self.create()
        self.assertEqual(gat.run(self.instance,synthesizer=self.synth)['citations'][0]['path'],'a.md')
        (self.habitat/'archive').mkdir()
        (self.habitat/'a.md').rename(self.habitat/'archive'/'b.md')
        result = gat.run(self.instance,synthesizer=self.synth)
        self.assertEqual(result['citations'][0]['path'],'archive/b.md')
        gat.set_paused(self.instance, True)
        model = Mock(side_effect=AssertionError('Must not call model'))
        with self.assertRaises(RuntimeError): gat.run(self.instance,synthesizer=model)
        model.assert_not_called()
        gat.set_paused(self.instance, False)
        self.assertEqual(gat.run(self.instance,synthesizer=self.synth)['discovery_entries'],0)

    def test_move_during_synthesis_skips_oversized_decoy_and_reuses_binding(self):
        self.create();size=len((self.habitat/'a.md').read_bytes())
        def moving_synth(question,documents):
            (self.habitat/'a.md').rename(self.habitat/'moved.md')
            (self.habitat/'decoy.md').write_text('x'*70000)
            return self.synth(question,documents)
        result=gat.run(self.instance,synthesizer=moving_synth)
        self.assertEqual(result['citations'][0]['path'],'moved.md')
        self.assertEqual(result['document_bytes_read'],3*size)
        restarted=gat.run(self.instance,synthesizer=self.synth)
        self.assertEqual(restarted['discovery_entries'],0)
        self.assertEqual(restarted['document_bytes_read'],2*size)

    def test_controls_without_habitat(self):
        self.create()
        self.habitat.rename(self.root/'offline')
        gat.set_paused(self.instance, True)
        self.assertEqual(gat.status(self.instance)['lifecycle'],'paused')

    def test_failed_enrollment_and_no_overwrite(self):
        with self.assertRaises((ValueError,OSError)):
            gat.create(self.instance,self.habitat,{'missing':'missing.md'},'Read')
        self.assertFalse((self.instance/'lifecycle.json').exists())
        with self.assertRaises((ValueError,OSError)): gat.run(self.instance,synthesizer=self.synth)
        with self.assertRaises(FileExistsError): self.create()

    def test_lock_and_malformed_lifecycle(self):
        self.create()
        with locked(self.instance):
            with self.assertRaises(RuntimeError): gat.run(self.instance,synthesizer=self.synth)
        (self.instance/'lifecycle.json').write_text('{}')
        with self.assertRaises(ValueError): gat.set_paused(self.instance, False)

    def test_reject_nested_invalid_and_duplicate_manifest(self):
        with self.assertRaises(ValueError):
            gat.create(self.habitat/'agent',self.habitat,{'a':'a.md'},'Read')
        with self.assertRaises(ValueError):
            gat.create(self.instance,self.habitat,{'a':'a.md'},'')
        self.assertFalse(self.instance.exists())
        self.create()
        path=self.instance/'instance.json'
        path.write_text(path.read_text().replace('"format":','"format":"duplicate", "format":',1))
        with self.assertRaises(ValueError): gat.status(self.instance)


    def test_cli_status_remains_distinct_from_memory_status(self):
        self.create()
        def command(*args):
            output=io.StringIO()
            with patch('sys.argv',['gat',*map(str,args)]),contextlib.redirect_stdout(output):
                self.assertEqual(gat.main(),0)
            return json.loads(output.getvalue())
        self.assertEqual(command('status',self.instance)['lifecycle'],'active')
        reservoir=self.root/'reservoir';reservoir.mkdir()
        command('memory-configure',self.instance,'--reservoir',reservoir,'--cycles','1')
        self.assertTrue(command('memory-status',self.instance)['enabled'])
        self.assertEqual(command('status',self.instance)['lifecycle'],'active')
        self.assertFalse(command('memory-disable',self.instance)['enabled'])
        command('pause',self.instance)
        self.assertEqual(command('status',self.instance)['lifecycle'],'paused')

if __name__=='__main__': unittest.main()
