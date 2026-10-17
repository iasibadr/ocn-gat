import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core.bridge_repair import LocalBridgeRepairer


class ResponseAuditTests(unittest.TestCase):
    @patch('ocn_core.bridge_repair.require_model',return_value={'digest':'test-digest'})
    @patch('ocn_core.bridge_repair.urllib.request.urlopen')
    def test_invalid_python_response_retained_before_validation(self,urlopen,catalogue):
        content=json.dumps({'source':'def build_synthesizer(model):\\n    return None'})
        response=dict(done=True,done_reason='stop',prompt_eval_count=100,eval_count=20,message={'content':content})
        raw=json.dumps(response).encode()
        urlopen.return_value.__enter__.return_value.read.return_value=raw
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'response.json';proposer=LocalBridgeRepairer('test');proposer.audit_path=path
            with self.assertRaisesRegex(ValueError,'Invalid UTF-8 Python source'):
                proposer('def build_synthesizer(model): return None','Contract','build_synthesizer')
            archived=json.loads(path.read_text())
            self.assertEqual(archived['response_utf8'].encode(),raw)
            urlopen.assert_called_once()

    @patch('ocn_core.bridge_repair.require_model',return_value={'digest':'test-digest'})
    @patch('ocn_core.bridge_repair.urllib.request.urlopen')
    def test_existing_audit_not_overwritten(self,urlopen,catalogue):
        urlopen.return_value.__enter__.return_value.read.return_value=b'{}'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'response.json';path.write_text('existing')
            proposer=LocalBridgeRepairer('test');proposer.audit_path=path
            with self.assertRaises(FileExistsError):proposer('source','contract','build_synthesizer')
            self.assertEqual(path.read_text(),'existing')

    @patch('ocn_core.bridge_repair.require_model',return_value={'digest':'test-digest'})
    @patch('ocn_core.bridge_repair.urllib.request.urlopen')
    def test_http_error_body_archived_without_retry(self,urlopen,catalogue):
        import io
        from urllib.error import HTTPError
        urlopen.side_effect=HTTPError('http://127.0.0.1:11434/api/chat',500,'error',{},io.BytesIO(b'{"error":"grammar rejected"}'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'response.json';proposer=LocalBridgeRepairer('test');proposer.audit_path=path
            with self.assertRaises(HTTPError):proposer('source','contract','build_synthesizer')
            report=json.loads(path.read_text())
            self.assertEqual(report['http_status'],500)
            self.assertEqual(report['error_body'],'{"error":"grammar rejected"}')
            urlopen.assert_called_once()

if __name__=='__main__':unittest.main()
