import json,tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_skill_session import DocumentSkillSession


class DocumentSkillTests(unittest.TestCase):
    def test_unsupported_shape_delegation_keeps_source_checks(self):
        (self.docs/'list.txt').write_text('{"id":"list","mass":["100 g"],"note":null}')
        self.adapter.bind('list','list.txt')
        s=DocumentSkillSession(self.adapter,lambda c,r,d,i,e:{'value':d['mass'][0]},
            lambda c,r,d,i,o:o['value']=='100 g',identity_guard=lambda c,r,d,i:d['id']==i,
            adapt_schema_changes=True,delegate_unsupported_shapes=True)
        s.permit('inventory','1')
        result=self.answer(s,'list')
        self.assertEqual(result['source']['document_id'],'list')
        self.assertEqual(result['learning'],'unsupported_observation')
        self.assertEqual(s.skills.examples,{})

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.adapter=DocumentAdapter(self.docs,self.root/'bindings.json')
        for n in range(1,5):
            (self.docs/f'{n}.txt').write_text(json.dumps({'id':str(n),'mass':f'{n*100} g'}))
            self.adapter.bind(str(n),f'{n}.txt')

    def session(self,worker=None,evaluate=None):
        s=DocumentSkillSession(self.adapter,worker or (lambda c,r,d,i,e:{'value':d['mass']}),
            evaluate or (lambda c,r,d,i,o:o['value']==f'{int(i)*100} g'),
            identity_guard=lambda c,r,d,i:d.get('id')==i,adapt_schema_changes=True)
        s.permit('inventory','1');return s

    def answer(self,s,n):
        return s.answer(str(n),connector='inventory',revision='1',identity=str(n),
                        allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)

    def test_learn_then_relocate_new_documents_without_model(self):
        s=self.session();self.answer(s,1);self.answer(s,2)
        (self.docs/'moved').mkdir()
        for n in (3,4):(self.docs/f'{n}.txt').rename(self.docs/'moved'/f'{n}.txt')
        a=self.answer(s,3);b=self.answer(s,4)
        self.assertEqual((a['action'],b['action']),('acquire_apply','apply'))
        self.assertEqual(b['source']['path'],'moved/4.txt')
        self.assertEqual(s.skills.worker_calls,2)

    def test_source_change_during_worker_does_not_train(self):
        def worker(c,r,d,i,e):
            (self.docs/'1.txt').write_text('changed')
            return {'value':'100 g'}
        s=self.session(worker=worker)
        with self.assertRaises(ValueError):self.answer(s,1)
        self.assertEqual(s.skills.examples,{})
        self.assertEqual(s.skills.worker_calls,1)

    def test_source_change_inside_evaluator_does_not_train(self):
        def evaluator(*args):
            (self.docs/'1.txt').write_text('changed during evaluation')
            return True
        s=self.session(evaluate=evaluator)
        with self.assertRaises(ValueError):self.answer(s,1)
        self.assertEqual(s.skills.examples,{})

    def test_duplicate_keys_and_wrong_identity_block_before_worker(self):
        (self.docs/'bad.txt').write_text('{"id":"bad","id":"other","mass":"1 g"}')
        self.adapter.bind('bad','bad.txt');s=self.session()
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.answer(s,'bad')
        with self.assertRaisesRegex(ValueError,'identity'):
            s.answer('1',connector='inventory',revision='1',identity='other',allowance=12,
                     acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(s.skills.worker_calls,0)

    def test_reentrant_request_cannot_replace_active_source(self):
        def worker(c,r,d,i,e):
            with self.assertRaisesRegex(RuntimeError,'busy'):self.answer(s,2)
            return {'value':d['mass']}
        s=self.session(worker=worker)
        self.assertEqual(self.answer(s,1)['source']['document_id'],'1')

if __name__=='__main__':unittest.main()
