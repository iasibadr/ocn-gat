import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import Agent,DNA,DirectoryHabitat,save_checkpoint,load_checkpoint
from ocn_core.checkpoint import canonical,MAX_BYTES
from ocn_core.controller import POLICIES

class CheckpointTests(unittest.TestCase):
    def test_restart_exact_trajectory_all_policies(self):
        for policy in POLICIES:
            with self.subTest(policy=policy),tempfile.TemporaryDirectory() as root:
                p=Path(root);h=p/'habitat';h.mkdir();dna=DNA(max_calls=5,max_cache=1,source_ids=('one',))
                uninterrupted=Agent(policy,{'one':'v0.json'},dna,seed=19)
                resumed=Agent(policy,{'one':'v0.json'},dna,seed=19)
                previous=None
                for n in range(40):
                    filename=f'v{n//7}.json'
                    if previous and previous!=filename:(h/previous).unlink()
                    previous=filename
                    alternate=(n//5)%2
                    doc={'source':'one','step':n}
                    doc.update({'data':{'measure':n+5}} if alternate else {'value':n+5})
                    (h/filename).write_text(json.dumps(doc))
                    (h/'directory.json').write_text(json.dumps({'one':filename}))
                    (h/'schemas.json').write_text(json.dumps({'one':{'codec':'integer','value_path':['data','measure'] if alternate else ['value']}}))
                    self.assertEqual(uninterrupted.step(n,DirectoryHabitat(h,dna)),resumed.step(n,DirectoryHabitat(h,dna)))
                    save_checkpoint(resumed,p/'state.json')
                    resumed=load_checkpoint(p/'state.json',dna,policy)

    def test_corruption_and_configuration_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'state';dna=DNA();a=Agent('ocn_hamilton',dict(zip(dna.source_ids,('a','b','c'))),dna)
            save_checkpoint(a,p)
            with self.assertRaises(ValueError):load_checkpoint(p,DNA(max_calls=10),'ocn_hamilton')
            with self.assertRaises(ValueError):load_checkpoint(p,dna,'reactive')
            raw=p.read_bytes();p.write_bytes(raw[:-8])
            with self.assertRaises(ValueError):load_checkpoint(p,dna,'ocn_hamilton')

    def test_structurally_invalid_even_with_checksum(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'state';dna=DNA();a=Agent('ocn_hamilton',dict(zip(dna.source_ids,('a','b','c'))),dna)
            save_checkpoint(a,p);original=p.read_text()
            mutations=[lambda d:d.update(version=2),lambda d:d.update(last_step=True),lambda d:d['paths'].update(alpha='../outside'),lambda d:d['predictor'].update(a=[[0]]),lambda d:d['errors'].update(alpha=2),lambda d:d['rng'][1].__setitem__(0,-1)]
            for mutate in mutations:
                doc=json.loads(original);mutate(doc['payload']);doc['sha256']=hashlib.sha256(canonical(doc['payload'])).hexdigest();p.write_bytes(canonical(doc))
                with self.assertRaises(ValueError):load_checkpoint(p,dna,'ocn_hamilton')
            p.write_bytes(b' '*(MAX_BYTES+1))
            with self.assertRaises(ValueError):load_checkpoint(p,dna,'ocn_hamilton')

    def test_failed_replace_preserves_old_state_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'state';dna=DNA();a=Agent('reactive',dict(zip(dna.source_ids,('a','b','c'))),dna)
            save_checkpoint(a,p);original=p.read_bytes();a.temperature=.1
            with patch('ocn_core.checkpoint.os.replace',side_effect=OSError('injected interruption')):
                with self.assertRaises(OSError):save_checkpoint(a,p)
            self.assertEqual(p.read_bytes(),original);self.assertEqual(list(Path(root).iterdir()),[p])
            self.assertEqual(load_checkpoint(p,dna,'reactive').temperature,.04)

    def test_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'state';p.write_text('{"payload":{},"payload":{},"sha256":"x"}')
            with self.assertRaises(ValueError):load_checkpoint(p,DNA(),'reactive')

    def test_cli_two_processes_and_repeated_step(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir()
            (h/'directory.json').write_text(json.dumps({'one':'new.json'}))
            (h/'schemas.json').write_text(json.dumps({'one':{'codec':'integer','value_path':['data','measure']}}))
            command=[sys.executable,'-c','from ocn_core.cli import main; raise SystemExit(main())',str(h),'--source','one=old.json','--budget','4','--policy','reactive','--state',str(p/'state')]
            for n,cost in [(0,4),(1,1)]:
                (h/'new.json').write_text(json.dumps({'source':'one','step':n,'data':{'measure':42}}))
                r=subprocess.run(command+['--step',str(n)],capture_output=True,text=True,check=True)
                result=json.loads(r.stdout);self.assertEqual(result['output']['sum'],42);self.assertEqual(result['cost'],cost)
            r=subprocess.run(command+['--step','1'],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn('strictly increasing',r.stderr)
            inside=command.copy();inside[-1]=str(h/'state')
            r=subprocess.run(inside,capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertFalse((h/'state').exists())

if __name__=='__main__':unittest.main()
