import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from ocn_core.archive_publication import publish


class ArchivePublicationTests(unittest.TestCase):
    def test_process_exit_during_write_leaves_no_final_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'archive.json'
            script="""import os,sys
from pathlib import Path
from ocn_core.archive_publication import publish
original=os.fdopen
class Interrupted:
    def __init__(self,stream):self.stream=stream
    def __enter__(self):return self
    def __exit__(self,*args):self.stream.close()
    def write(self,raw):
        self.stream.write(raw[:3]);self.stream.flush();os._exit(73)
os.fdopen=lambda *args,**kwargs:Interrupted(original(*args,**kwargs))
publish(Path(sys.argv[1]),b'complete bytes')
"""
            result=subprocess.run([sys.executable,'-c',script,str(path)],timeout=20,capture_output=True)
            self.assertEqual(result.returncode,73);self.assertFalse(path.exists())
            leftovers=list(Path(tmp).iterdir());self.assertEqual(len(leftovers),1)
            self.assertTrue(leftovers[0].name.startswith('.archive-pending-'))
            self.assertEqual(leftovers[0].read_bytes(),b'com')
            publish(path,b'complete bytes');self.assertEqual(path.read_bytes(),b'complete bytes')
            self.assertTrue(leftovers[0].exists())  # Never delete unknown crash state.

    def test_publication_reserves_both_directory_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(255):(root/str(i)).touch()
            with self.assertRaisesRegex(ValueError,'capacity'):publish(root/'new.json',b'new')
            self.assertEqual(len(list(root.iterdir())),255)
            publish(root/'0',b'ignored')  # Existing bytes remain for caller verification.
            self.assertEqual((root/'0').read_bytes(),b'')

    def test_concurrent_final_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'archive.json';original=os.link
            def race(source,destination,**kwargs):
                path.write_bytes(b'other writer')
                return original(source,destination,**kwargs)
            with patch('ocn_core.archive_publication.os.link',side_effect=race):publish(path,b'ours')
            self.assertEqual(path.read_bytes(),b'other writer')
            self.assertEqual(list(Path(tmp).iterdir()),[path])

if __name__=='__main__':unittest.main()
