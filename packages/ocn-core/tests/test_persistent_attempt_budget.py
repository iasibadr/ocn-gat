import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from ocn_core.model_budget import PersistentAttemptBudget
from unittest.mock import patch

class Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
    def test_reopen_never_resets_and_create_is_exclusive(self):
        b=PersistentAttemptBudget.create(self.root,2);b.reserve()
        with self.assertRaises(FileExistsError):PersistentAttemptBudget.create(self.root,2)
        other=PersistentAttemptBudget(self.root,2);self.assertEqual(other.snapshot()['used'],1)
        other.reserve()
        with self.assertRaises(RuntimeError):b.reserve()
        with self.assertRaises(ValueError):PersistentAttemptBudget(self.root,3)
    def test_concurrent_processes_cannot_overspend(self):
        b=PersistentAttemptBudget.create(self.root,6)
        code='''from ocn_core.model_budget import PersistentAttemptBudget
import sys
b=PersistentAttemptBudget(sys.argv[1],6)
n=0
for _ in range(6):
 try:b.reserve();n+=1
 except RuntimeError:break
print(n)
'''
        children=[subprocess.Popen([sys.executable,'-c',code,str(self.root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
        counts=[]
        for child in children:
            out,err=child.communicate(timeout=20);self.assertEqual(child.returncode,0,err);counts.append(int(out))
        self.assertEqual(sum(counts),6);self.assertEqual(b.snapshot()['used'],6)
    def test_uncertain_durable_write_does_not_refund(self):
        b=PersistentAttemptBudget.create(self.root,1)
        with patch('ocn_core.model_budget.sync_directory',side_effect=OSError('fsync failed')):
            with self.assertRaises(OSError):b.reserve()
        self.assertEqual(b.snapshot()['used'],1)
        with self.assertRaises(RuntimeError):b.reserve()
    def test_lock_symlink_rejected(self):
        b=PersistentAttemptBudget.create(self.root,1)
        lock=self.root/'model-budget.lock';lock.unlink();(self.root/'other').write_text('x');lock.symlink_to(self.root/'other')
        with self.assertRaises(OSError):b.reserve()

if __name__=='__main__':unittest.main()
