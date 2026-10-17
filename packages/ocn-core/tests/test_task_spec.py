from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import Agent,DNA,DirectoryHabitat,TaskSpec,ToolSession,load_checkpoint

class TaskSpecTests(unittest.TestCase):
    def test_ordered_difference_and_negative_extrema(self):
        values={'a':-4,'b':9}
        for operation,expected in (('sum',5),('minimum',-4),('maximum',9),('difference',-13)):
            self.assertEqual(TaskSpec(operation,('a','b')).evaluate(values),expected)
        self.assertEqual(TaskSpec('difference',('b','a')).evaluate(values),13)
        with self.assertRaises(ValueError):TaskSpec('sum',('a','b')).evaluate({'a':False,'b':9})
        with self.assertRaises(ValueError):TaskSpec('sum',('a','b')).evaluate({'a':-4})

    def test_task_is_frozen_and_rejects_arbitrary_expressions(self):
        task=TaskSpec('sum',('a','b'))
        with self.assertRaises(FrozenInstanceError):task.operation='maximum'
        for operation,sources in (('eval',('a',)),('difference',('a',)),('sum',()),('sum',('a','a'))):
            with self.assertRaises(ValueError):TaskSpec(operation,sources)

    def test_subset_limits_tools_and_can_change_between_persisted_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();dna=DNA(source_ids=('a','b'),max_cache=2,max_calls=4)
            agent=Agent('reactive',{'a':'a','b':'b'},dna)
            (h/'b').write_text(json.dumps(dict(source='b',step=0,value=9)))
            s=ToolSession(agent,DirectoryHabitat(h,dna),0,task=TaskSpec('maximum',('b',)))
            self.assertEqual(s.execute(dict(op='read',source='a',path='a',value=0))['error'],'denied_source')
            self.assertEqual(s.tools.calls,[])
            with self.assertRaises(AttributeError):s.task=TaskSpec('sum',('a','b'))
            feedback=s.execute(dict(op='finish',path='',value=9))
            self.assertEqual(feedback['reason'],'missing_evidence')
            self.assertEqual(feedback['verified_inputs'],[])
            self.assertEqual(feedback['missing_sources'],['b'])
            s.execute(dict(op='read',path='b',value=0));s.execute(dict(op='finish',path='',value=9))
            result=s.persist(root/'state');self.assertEqual(result['task']['operation'],'maximum')
            agent=load_checkpoint(root/'state',dna,'reactive')
            for source,value in (('a',-4),('b',9)):
                (h/source).write_text(json.dumps(dict(source=source,step=1,value=value)))
            s=ToolSession(agent,DirectoryHabitat(h,dna),1,task=TaskSpec('difference',('b','a')))
            for source in ('a','b'):s.execute(dict(op='read',source=source,path=source,value=0))
            feedback=s.execute(dict(op='finish',path='',value=5))
            self.assertEqual(feedback,dict(ok=False,error='unverified_answer',reason='task_mismatch',
                task=dict(operation='difference',sources=['b','a']),
                verified_inputs=[dict(source='b',value=9),dict(source='a',value=-4)],missing_sources=[]))
            self.assertFalse(s.done)
            self.assertTrue(s.execute(dict(op='finish',path='',value=13))['ok'])
            self.assertEqual(s.persist(root/'state')['answer'],13)

    def test_outside_dna_rejected_before_session_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dna=DNA(source_ids=('a',),max_cache=1)
            agent=Agent('reactive',{'a':'a'},dna);tools=DirectoryHabitat(root,dna)
            with self.assertRaises(ValueError):ToolSession(agent,tools,0,task=TaskSpec('sum',('b',)))
            self.assertEqual(agent.last_step,-1);self.assertEqual(tools.calls,[])
            self.assertIsNone(getattr(agent,'_tool_session',None))

if __name__=='__main__':unittest.main()
