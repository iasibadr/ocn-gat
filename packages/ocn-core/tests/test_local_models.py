import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core.local_models import installed_models,require_model
from ocn_core.application import create,run,set_paused

class LocalModelsTests(unittest.TestCase):
    def response(self,models):return io.BytesIO(json.dumps(dict(models=models)).encode())
    def test_catalogue_selection_and_missing_identifier(self):
        item=dict(name='local:one',digest='hash',size=42)
        with patch('ocn_core.local_models.urllib.request.urlopen',return_value=self.response([item])):
            self.assertEqual(installed_models(),[dict(name='local:one',digest='hash',size_bytes=42)])
        with patch('ocn_core.local_models.installed_models',return_value=[dict(name='local:one',digest='hash',size_bytes=42)]):
            self.assertEqual(require_model('local:one')['digest'],'hash')
            with self.assertRaises(ValueError):require_model('not-installed')
    def test_reject_ambiguous_or_malformed_catalogue(self):
        item=dict(name='local:one',digest='hash',size=42)
        for entries in [[item,item],[item|dict(size=True)],[item|dict(digest='')],['bad']]:
            with patch('ocn_core.local_models.urllib.request.urlopen',return_value=self.response(entries)):
                with self.assertRaises(ValueError):installed_models()
    def test_preflight_failure_does_not_create_task_state_or_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();instance=root/'agent';create(instance,h,{'s':'s.json'})
            with patch('ocn_core.local_models.installed_models',return_value=[]):
                with self.assertRaises(ValueError):run(instance,0)
            self.assertFalse((instance/'state.json').exists())
            self.assertFalse((instance/'reservoir.sqlite').exists())
            set_paused(instance,True)
            with patch('ocn_core.local_models.installed_models') as catalogue:
                with self.assertRaises(RuntimeError):run(instance,0)
                catalogue.assert_not_called()

if __name__=='__main__':unittest.main()
