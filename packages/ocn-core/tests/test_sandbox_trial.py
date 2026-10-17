import unittest
from unittest.mock import patch
from ocn_core.agent_integration import Integration
from ocn_core.sandbox_trial import run_trial


class SandboxPreflightTests(unittest.TestCase):
    def setUp(self):
        self.integration=Integration(b'def build_synthesizer(model):\n    return lambda question, documents: question\n','build_synthesizer')

    def test_missing_bubblewrap_never_falls_back_to_host(self):
        with patch('ocn_core.sandbox_trial.shutil.which',return_value=None),patch('ocn_core.sandbox_trial.subprocess.Popen') as process:
            with self.assertRaisesRegex(RuntimeError,'host execution is forbidden'):
                run_trial(self.integration,model='fixture',question='test',documents=[])
            process.assert_not_called()

    def test_invalid_limits_or_oversized_fixture_cannot_start(self):
        with patch('ocn_core.sandbox_trial.subprocess.Popen') as process:
            for timeout in (0,11,True):
                with self.assertRaises(ValueError):
                    run_trial(self.integration,model='fixture',question='test',documents=[],timeout_seconds=timeout)
            with self.assertRaisesRegex(ValueError,'fixture too large'):
                run_trial(self.integration,model='fixture',question='x'*70000,documents=[])
            process.assert_not_called()

if __name__=='__main__':unittest.main()
