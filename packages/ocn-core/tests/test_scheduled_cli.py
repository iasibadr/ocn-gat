import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ocn_core import CompactReservoir

class ScheduledCLITests(unittest.TestCase):
    def command(self,h,*args):
        return [sys.executable,'-c','from ocn_core.cli import main; raise SystemExit(main())',str(h),'--source','s=old',*map(str,args)]
    def invoke(self,h,*args):
        return subprocess.run(self.command(h,*args),capture_output=True,text=True)
    def test_real_process_acquisition_reuse_and_dissipation(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir()
            (h/'directory.json').write_text(json.dumps({'s':'new'}))
            (h/'schemas.json').write_text(json.dumps({'s':dict(codec='decimal_integer',value_path=['amount'])}))
            options=('--scheduler','ocn_hamilton','--state',p/'state','--reservoir',p/'sink','--budget','5','--allow-decimal')
            outputs=[]
            for n in (0,1,8):
                (h/'new').write_text(json.dumps(dict(source='s',step=n,amount='42')))
                r=self.invoke(h,*options,'--step',n)
                self.assertEqual(r.returncode,0,r.stderr);outputs.append(json.loads(r.stdout))
                self.assertEqual(outputs[-1]['output']['sum'],42)
            self.assertEqual(outputs[0]['cost'],4)
            self.assertEqual(outputs[1]['cost'],1)
            self.assertEqual(outputs[2]['cost'],2)
            state=json.loads((p/'state').read_text())['payload']
            self.assertEqual(state['policy'],'reactive');self.assertEqual(state['version'],5)
            self.assertEqual(state['retirement']['accepted_events'],2)
            self.assertEqual(state['emission']['state']['born'],{})
            self.assertEqual(CompactReservoir(p/'sink',16).status()['load'],1)
            before=(p/'state').read_bytes()
            r=self.invoke(h,*options,'--step',9,'--reaction-horizon','4')
            self.assertNotEqual(r.returncode,0);self.assertIn('DNA mismatch',r.stderr)
            self.assertEqual((p/'state').read_bytes(),before)
    def test_invalid_combinations_have_no_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir()
            variants=[('--repack-refused',),('--scheduler','ocn_hamilton'),('--reservoir',p/'sink'),
                      ('--scheduler','backoff','--state',p/'same','--reservoir',p/'same'),
                      ('--scheduler','backoff','--state',h/'state','--reservoir',p/'sink'),
                      ('--scheduler','backoff','--state',p/'state','--reservoir',p/'sink','--reaction-horizon','0')]
            for args in variants:
                r=self.invoke(h,*args);self.assertEqual(r.returncode,2)
                self.assertEqual(list(h.iterdir()),[])
                self.assertEqual(sorted(x.name for x in p.iterdir()),['h'])
    def test_incompatible_existing_policy_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir()
            (h/'old').write_text(json.dumps(dict(source='s',step=0,value=1)))
            r=self.invoke(h,'--state',p/'state','--policy','ocn_hamilton')
            self.assertEqual(r.returncode,0,r.stderr)
            before=(p/'state').read_bytes()
            r=self.invoke(h,'--state',p/'state','--step',1)
            self.assertEqual(r.returncode,2);self.assertIn('policy mismatch',r.stderr)
            self.assertEqual((p/'state').read_bytes(),before)

    def test_repacking_cli_persists_opt_in_and_rejects_removal(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);h=p/'h';h.mkdir()
            options=('--scheduler','backoff','--state',p/'state','--reservoir',p/'sink')
            for n in (0,1):
                (h/'old').write_text(json.dumps(dict(source='s',step=n,value=42)))
                r=self.invoke(h,*options,'--repack-refused','--step',n)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(json.loads(r.stdout)['output']['sum'],42)
            payload=json.loads((p/'state').read_text())['payload']
            self.assertEqual(payload['version'],6)
            self.assertEqual(payload['dna']['refusal_contract'],'atomic_nonacceptance_v1')
            before=(p/'state').read_bytes()
            r=self.invoke(h,*options,'--step',2)
            self.assertEqual(r.returncode,2)
            self.assertEqual((p/'state').read_bytes(),before)

    def test_paced_cli_emits_at_persisted_interval(self):
        for period in (16,32):
            with self.subTest(period=period),tempfile.TemporaryDirectory() as root:
                p=Path(root);h=p/'h';h.mkdir()
                (h/'directory.json').write_text(json.dumps({'s':'new'}))
                options=('--scheduler',f'paced{period}','--state',p/'state','--reservoir',p/'sink','--budget','4','--repack-refused')
                outputs=[]
                for n in (0,period):
                    (h/'new').write_text(json.dumps(dict(source='s',step=n,value=42)))
                    r=self.invoke(h,*options,'--step',n)
                    self.assertEqual(r.returncode,0,r.stderr)
                    outputs.append(json.loads(r.stdout))
                self.assertEqual(outputs[0]['dissipation']['accepted_events'],0)
                self.assertEqual(outputs[1]['dissipation']['accepted_events'],1)
                self.assertEqual(outputs[1]['cost'],2)
                payload=json.loads((p/'state').read_text())['payload']
                self.assertEqual(payload['dna']['scheduler'],f'paced{period}')

if __name__=='__main__':unittest.main()
