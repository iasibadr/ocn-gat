import json
from pathlib import Path
import tempfile
import unittest
from ocn_core import Agent,DNA,DirectoryHabitat,ToolSession,TaskSpec

class EvaluationTests(unittest.TestCase):
    def test_evaluation_requires_current_proofs_and_is_charged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dna=DNA(source_ids=('a','b'),max_cache=2,max_calls=4)
            for source,value in [('a',-5),('b',20)]:
                (root/source).write_text(json.dumps(dict(source=source,step=0,value=value)))
            agent=Agent('reactive',{'a':'a','b':'b'},dna);tools=DirectoryHabitat(root,dna)
            session=ToolSession(agent,tools,0,max_decisions=10,task=TaskSpec('difference',('b','a')))
            evaluate=dict(op='evaluate',path='',value=0)
            self.assertEqual(session.execute(evaluate)['error'],'missing_evidence')
            self.assertEqual(len(tools.calls),0)
            for source in ('a','b'):session.execute(dict(op='read',source=source,path=source,value=0))
            self.assertEqual(session.execute(evaluate),dict(ok=True,result=25))
            self.assertEqual(len(tools.calls),3);self.assertFalse(session.done)
            (root/'b').write_text(json.dumps(dict(source='b',step=0,value='bad')))
            session.execute(dict(op='read',source='b',path='b',value=0))
            self.assertEqual(session.execute(evaluate)['error'],'missing_evidence')
            self.assertEqual(len(tools.calls),4)

    def test_budget_and_argument_validation_do_not_fabricate_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dna=DNA(source_ids=('a',),max_cache=1,max_calls=1)
            (root/'a').write_text(json.dumps(dict(source='a',step=0,value=7)))
            session=ToolSession(Agent('reactive',{'a':'a'},dna),DirectoryHabitat(root,dna),0)
            self.assertEqual(session.execute(dict(op='evaluate',path='expression',value=0))['error'],'invalid_action')
            session.execute(dict(op='read',path='a',value=0))
            self.assertEqual(session.execute(dict(op='evaluate',path='',value=0))['error'],'budget')
            self.assertFalse(session.done)
            self.assertTrue(session.execute(dict(op='finish',path='',value=7))['ok'])

if __name__=='__main__':unittest.main()
