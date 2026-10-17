import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import Agent,DNA,DirectoryHabitat,ToolSession,TaskSpec,load_checkpoint,recover_task_receipt,save_checkpoint
from ocn_core.checkpoint import canonical

class ReceiptTests(unittest.TestCase):
    def setup_task(self,root,request_id='a'*32,step=0,agent=None):
        h=root/'h';h.mkdir(exist_ok=True)
        dna=DNA(source_ids=('s',),max_cache=1)
        agent=agent or Agent('reactive',{'s':'data.json'},dna)
        (h/'data.json').write_text(json.dumps(dict(source='s',step=step,value=41)))
        session=ToolSession(agent,DirectoryHabitat(h,dna),step,request_id=request_id)
        return session,dna
    def recover(self,path,dna,**kwargs):
        return recover_task_receipt(path,dna,'reactive',request_id=kwargs.get('request_id','a'*32),step=kwargs.get('step',0),task=kwargs.get('task',TaskSpec('sum',('s',))))
    def finish(self,session):
        self.assertTrue(session.execute(dict(op='read',path='data.json',value=0))['ok'])
        self.assertTrue(session.execute(dict(op='finish',path='',value=41))['ok'])
    def test_recover_without_tools_and_prevent_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,dna=self.setup_task(root);self.finish(session);session.persist(root/'state')
            (root/'h'/'data.json').unlink()
            receipt=self.recover(root/'state',dna)
            self.assertEqual(receipt['outcome'],dict(done=True,refused=False,answer=41,error=None))
            restored=load_checkpoint(root/'state',dna,'reactive');tools=DirectoryHabitat(root/'h',dna)
            for task in (TaskSpec('sum',('s',)),TaskSpec('maximum',('s',))):
                with self.assertRaises(ValueError):ToolSession(restored,tools,1,task=task,request_id='a'*32)
            self.assertEqual(tools.calls,[]);self.assertEqual(restored.last_step,0)
            for options in ({'request_id':'b'*32},{'step':1},{'task':TaskSpec('maximum',('s',))},{'step':False}):
                with self.assertRaises(ValueError):self.recover(root/'state',dna,**options)
            with self.assertRaises(ValueError):recover_task_receipt(root/'state',DNA(source_ids=('other',),max_cache=1),'reactive',request_id='a'*32,step=0,task=TaskSpec('sum',('s',)))
    def test_new_task_does_not_inherit_proofs_and_replaces_latest_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,dna=self.setup_task(root);self.finish(session);session.persist(root/'state')
            agent=load_checkpoint(root/'state',dna,'reactive')
            new,_=self.setup_task(root,request_id='b'*32,step=1,agent=agent)
            self.assertEqual(new.verified,{})
            self.assertFalse(new.execute(dict(op='finish',path='',value=41))['ok'])
            self.finish(new);new.persist(root/'state')
            self.assertEqual(self.recover(root/'state',dna,request_id='b'*32,step=1)['outcome']['answer'],41)
            with self.assertRaises(ValueError):self.recover(root/'state',dna)
    def test_failed_replace_keeps_previous_receipt_and_poisoned_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,dna=self.setup_task(root);self.finish(session);session.persist(root/'state');before=(root/'state').read_bytes()
            new,_=self.setup_task(root,request_id='b'*32,step=1,agent=load_checkpoint(root/'state',dna,'reactive'));self.finish(new)
            with patch('ocn_core.checkpoint.os.replace',side_effect=OSError('injected')):
                with self.assertRaises(OSError):new.persist(root/'state')
            self.assertEqual((root/'state').read_bytes(),before)
            self.assertEqual(self.recover(root/'state',dna)['outcome']['answer'],41)
            self.assertTrue(new.agent._tool_session_failed)
    def test_error_after_replace_requires_reload_and_keeps_committed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,dna=self.setup_task(root);self.finish(session)
            import os
            original=os.replace
            def replaced_then_failed(a,b):original(a,b);raise OSError('lost completion')
            with patch('ocn_core.checkpoint.os.replace',side_effect=replaced_then_failed):
                with self.assertRaises(OSError):session.persist(root/'state')
            self.assertEqual(self.recover(root/'state',dna)['outcome']['answer'],41)
            self.assertTrue(session.agent._tool_session_failed)
    def test_refusal_unfinished_and_legacy_absence(self):
        for state in ('refusal','unfinished','legacy'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);session,dna=self.setup_task(root,request_id=None if state=='legacy' else 'a'*32)
                if state=='refusal':
                    (root/'h'/'data.json').write_text('[]')
                    session.execute(dict(op='read',path='data.json',value=0));session.execute(dict(op='abstain',path='',value=0))
                session.persist(root/'state')
                if state=='legacy':
                    with self.assertRaises(ValueError):self.recover(root/'state',dna)
                    self.assertNotIn('format',json.loads((root/'state').read_text()))
                else:
                    outcome=self.recover(root/'state',dna)['outcome']
                    self.assertIsNone(outcome['answer']);self.assertEqual(outcome['done'],state=='refusal')
                    self.assertEqual(outcome['error'],'invalid_document' if state=='refusal' else None)
    def test_corruption_and_rehashed_semantic_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,dna=self.setup_task(root);self.finish(session);session.persist(root/'state')
            original=json.loads((root/'state').read_text())
            altered=copy.deepcopy(original);altered['receipt']['outcome']['answer']=99
            (root/'state').write_text(json.dumps(altered))
            with self.assertRaises(ValueError):self.recover(root/'state',dna)
            for mutate in (lambda r:r.update(step=99),lambda r:r.update(identity='bad'),lambda r:r['outcome'].update(answer=True),lambda r:r.update(request_id='bad')):
                doc=copy.deepcopy(original);mutate(doc['receipt'])
                doc['sha256']=hashlib.sha256(canonical({k:doc[k] for k in ('format','payload','receipt')})).hexdigest()
                (root/'state').write_text(json.dumps(doc))
                with self.assertRaises(ValueError):self.recover(root/'state',dna)
            doc=copy.deepcopy(original);doc['format']='unknown'
            (root/'state').write_text(json.dumps(doc))
            with self.assertRaises(ValueError):self.recover(root/'state',dna)
    def test_bad_request_ids_rejected_before_agent_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();dna=DNA(source_ids=('s',),max_cache=1);agent=Agent('reactive',{'s':'data.json'},dna)
            for request_id in ('',True,'../bad','A'*32,'a'*33):
                with self.assertRaises(ValueError):ToolSession(agent,DirectoryHabitat(h,dna),0,request_id=request_id)
                self.assertEqual(agent.last_step,-1)

if __name__=='__main__':unittest.main()
