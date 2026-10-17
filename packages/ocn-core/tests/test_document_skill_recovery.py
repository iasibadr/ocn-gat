import json,tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_skill_session import DocumentSkillSession

class DocumentRecoveryTests(unittest.TestCase):
 def exercise(self,mutation=None):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);docs=root/'docs';docs.mkdir();adapter=DocumentAdapter(docs,root/'pins')
   for i in range(4):
    (docs/f'{i}.txt').write_text(json.dumps({'id':str(i),'first':f'City {i}','second':f'Other {i}','current':'first' if i<3 else 'second'}));adapter.bind(str(i),f'{i}.txt')
   calls=[]
   def worker(c,r,d,i,e):
    calls.append(i)
    if i=='3' and mutation=='worker':(docs/'3.txt').write_text('changed')
    return {'value':d[d['current']]}
   def evaluate(c,r,d,i,o):
    if i=='3' and mutation=='verifier':(docs/'3.txt').write_text('changed')
    return o['value']==d[d['current']]
   s=DocumentSkillSession(adapter,worker,evaluate,identity_guard=lambda c,r,d,i:d['id']==i,
    adapt_schema_changes=True,skill_kind='text',retry_rejected_skill=True)
   s.permit('A','1')
   def answer(i):return s.answer(str(i),connector='A',revision='1',identity=str(i),allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)
   for i in range(3):answer(i)
   if mutation:
    with self.assertRaises(ValueError):answer(3)
    self.assertNotIn('A',s.skills.examples)
    self.assertEqual(len(calls),3 if mutation=='worker' else 2)
   else:
    result=answer(3);self.assertEqual(result['action'],'recover_delegate')
    self.assertEqual(result['output']['value'],'Other 3');self.assertEqual(result['source']['document_id'],'3')
 def test_recovery_stays_bound_to_document(self):self.exercise()
 def test_mutated_source_blocks_recovery_or_learning(self):
  for stage in ('worker','verifier'):self.exercise(stage)

if __name__=='__main__':unittest.main()
