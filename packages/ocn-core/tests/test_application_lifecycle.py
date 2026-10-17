import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core.application import create,run,status,set_paused,locked

class LifecycleTests(unittest.TestCase):
    def setup_instance(self,root):
        habitat=root/'h';habitat.mkdir();instance=root/'agent'
        create(instance,habitat,{'s':'s.json'})
        return instance,habitat
    def test_pause_persists_across_processes_without_model_or_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,h=self.setup_instance(Path(tmp));identity=status(instance)['identity']
            set_paused(instance,True);runner=Mock()
            with self.assertRaises(RuntimeError):run(instance,0,runner=runner)
            runner.assert_not_called();self.assertFalse((instance/'reservoir.sqlite').exists())
            child=subprocess.run([sys.executable,'-m','ocn_core.application','status',str(instance)],capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(child.stdout)['lifecycle'],'paused')
            self.assertFalse(set_paused(instance,True)['changed'])
            self.assertEqual(set_paused(instance,False)['lifecycle'],'active')
            self.assertEqual(status(instance)['identity'],identity)
    def test_missing_or_malformed_state_never_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,h=self.setup_instance(Path(tmp));path=instance/'lifecycle.json';path.unlink()
            self.assertEqual(status(instance)['lifecycle'],'uninitialized')
            runner=Mock()
            with self.assertRaises(RuntimeError):run(instance,0,runner=runner)
            set_paused(instance,False)
            for raw in ['{}','{"format":"ocn.lifecycle.v1","state":"paused","state":"active"}', 'not json']:
                path.write_text(raw)
                with self.assertRaises(ValueError):run(instance,0,runner=runner)
                with self.assertRaises(ValueError):set_paused(instance,False)
            runner.assert_not_called()
    def test_control_remains_available_when_habitat_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,h=self.setup_instance(Path(tmp));h.rmdir()
            self.assertEqual(set_paused(instance,True)['lifecycle'],'paused')
            self.assertEqual(status(instance)['lifecycle'],'paused')
    def test_failed_atomic_replacement_preserves_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,h=self.setup_instance(Path(tmp));set_paused(instance,True)
            before=(instance/'lifecycle.json').read_bytes()
            with patch('ocn_core.application.os.replace',side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):set_paused(instance,False)
            self.assertEqual((instance/'lifecycle.json').read_bytes(),before)
            self.assertEqual(list(instance.glob('.lifecycle-*')),[])
    def test_pause_during_execution_reports_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,h=self.setup_instance(Path(tmp))
            with locked(instance):
                with self.assertRaises(RuntimeError):set_paused(instance,True)
            self.assertEqual(status(instance)['lifecycle'],'active')

if __name__=='__main__':unittest.main()
