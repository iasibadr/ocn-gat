import json
from pathlib import Path
import tempfile
import unittest
from ocn_core.application import create,run,status,recover,locked
from ocn_core.controller import descriptor_digest

class ApplicationTests(unittest.TestCase):
    def test_create_run_move_restart_and_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();instance=root/'agent'
            descriptor=dict(codec='integer',value_path=['value'])
            def publish(step,path,value):
                (h/path).write_text(json.dumps(dict(source='s',step=step,value=value,schema_digest=descriptor_digest(descriptor))))
                (h/'directory.json').write_text(json.dumps({'s':path}))
            create(instance,h,{'s':'old.json'})
            calls=[]
            def runner(session,deadline,model_id):
                calls.append(model_id)
                path=session.agent.paths['s']
                response=session.execute(dict(op='read',source='s',path=path,value=0))
                if not response['ok']:
                    path=session.execute(dict(op='locate',source='s',path='',value=0))['result']
                    response=session.execute(dict(op='read',source='s',path=path,value=0))
                self.assertTrue(response['ok'])
                value=session.execute(dict(op='evaluate',path='',value=0))['result']
                self.assertTrue(session.execute(dict(op='finish',path='',value=value))['ok'])
                return dict(error=None,model_trace=[])
            publish(0,'old.json',41)
            identity=status(instance)['identity']
            self.assertEqual(run(instance,0,request_id='a'*32,runner=runner)['result']['answer'],41)
            (h/'old.json').unlink();publish(1,'moved.json',99)
            self.assertEqual(run(instance,1,request_id='b'*32,model='another-local-model',runner=runner)['result']['answer'],99)
            self.assertEqual(status(instance)['identity'],identity)
            self.assertEqual(status(instance)['paths']['s'],'moved.json')
            self.assertEqual(recover(instance,1,'b'*32)['outcome']['answer'],99)
            self.assertEqual(calls,['qwen3.5:9b','another-local-model'])
            with self.assertRaises(ValueError):recover(instance,0,'a'*32)
            with locked(instance):
                with self.assertRaises(RuntimeError):run(instance,2,runner=runner)
    def test_invalid_create_leaves_no_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();instance=root/'agent'
            with self.assertRaises(ValueError):create(instance,h,{'s':'s.json'},operation='unbounded')
            self.assertFalse(instance.exists())
            with self.assertRaises(ValueError):create(h/'nested',h,{'s':'s.json'})
            self.assertFalse((h/'nested').exists())

if __name__=='__main__':unittest.main()
