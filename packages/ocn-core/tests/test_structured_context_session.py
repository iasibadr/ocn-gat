import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.local_evidence_context import LocalEvidenceContextWorker
from ocn_core.structured_context_session import StructuredContextSession
CAPACITY='Prompt exceeds maximum conservative context allowance'

class StructuredTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.adapter=DocumentAdapter(self.docs,self.root/'state.json')
        self.pin=patch('ocn_core.local_evidence_context.require_model',return_value={'digest':'fixture'})
        self.pin.start();self.addCleanup(self.pin.stop)
        self.worker=LocalEvidenceContextWorker('fixture',max_calls=16)
        self.seen=[];self.reply=None;self.effect=None
        self.transport=patch('urllib.request.urlopen',side_effect=self.send)
        self.transport.start();self.addCleanup(self.transport.stop)
    def enroll(self,text='ZP21 livraison lundi. Validation requise.'):
        (self.docs/'a.md').write_text(text);self.adapter.bind('a','a.md')
    def send(self,request,**kwargs):
        payload=json.loads(request.data);task=json.loads(payload['messages'][1]['content']);self.seen.append(task)
        answer={key:dict(status='unknown',answer=None,references=[]) for key in task['fields']}
        ref=task['paragraphs'][0]['id']
        answer['f0_value']=dict(status='supported',answer='lundi',references=[ref])
        answer['f0_conditions']=dict(status='supported',answer='validation requise',references=[ref])
        if self.reply:answer=self.reply(task,answer)
        if self.effect:self.effect()
        return io.BytesIO(json.dumps(dict(done=True,done_reason='stop',prompt_eval_count=100,eval_count=40,message=dict(content=json.dumps(answer)))).encode())
    def ask(self,session,fields=None):
        return session.answer('Livraison ZP21 ?',fields if fields is not None else {'day':'Jour de livraison ZP21'},('a',))
    def test_composition_preserves_slots_provenance_and_nonverification(self):
        self.enroll();session=StructuredContextSession(self.adapter,self.worker)
        receipt=self.ask(session)
        self.assertEqual(receipt['fields']['day']['answer'],'lundi Conditions : validation requise')
        self.assertEqual(receipt['slot_map']['day']['exceptions'],'f0_exceptions')
        self.assertEqual(receipt['slot_fields']['f0_exceptions']['status'],'unknown')
        self.assertFalse(receipt['completeness_verified']);self.assertFalse(receipt['action_authorized'])
        self.assertEqual(receipt['context_routing']['model_calls'],1)
        receipt['context_routing']['routes'].append('modified')
        self.assertEqual(session.last_attempt()['routes'],['full'])
    def test_long_retrieval_uses_original_fields_and_move_is_recovered(self):
        self.enroll('ZP21 livraison lundi. Validation requise. '+('Inventaire décoratif sans rapport avec la demande. '*330))
        session=StructuredContextSession(self.adapter,self.worker,max_paragraphs=1024)
        first=self.ask(session)
        self.assertEqual(first['context_routing']['routes'],['full','source-windows'])
        self.assertLessEqual(len(self.seen[0]['paragraphs']),3)
        self.assertEqual(len(self.seen[0]['fields']),3)
        (self.docs/'a.md').rename(self.docs/'new.md');second=self.ask(session)
        self.assertEqual(second['sources']['a']['path'],'new.md')
        self.assertEqual(first['fields'],second['fields'])
        (self.docs/'new.md').write_text('Unauthorized replacement')
        with self.assertRaisesRegex(ValueError,'Enrolled version'):self.ask(session)
        self.assertEqual(self.worker.calls,2)
    def test_source_changed_during_inference_withholds_result(self):
        self.enroll();session=StructuredContextSession(self.adapter,self.worker)
        self.effect=lambda:(self.docs/'a.md').write_text('Changed')
        with self.assertRaisesRegex(ValueError,'Enrolled version'):self.ask(session)
        self.assertEqual(session.last_attempt()['status'],'failed');self.assertEqual(self.worker.calls,1)
    def test_unknown_primary_cannot_be_promoted(self):
        self.enroll();session=StructuredContextSession(self.adapter,self.worker)
        def reply(task,answer):answer['f0_value']=dict(status='unknown',answer=None,references=[]);return answer
        self.reply=reply;receipt=self.ask(session)
        self.assertEqual(receipt['fields']['day'],dict(status='unknown',answer=None,references=[]))
        self.assertEqual(receipt['slot_fields']['f0_conditions']['status'],'supported')
    def test_conflicting_condition_withholds_primary(self):
        self.enroll('ZP21 livraison lundi.\n\nZP21 autre note.')
        def reply(task,answer):answer['f0_conditions']=dict(status='conflicting',answer=None,references=[p['id'] for p in task['paragraphs']]);return answer
        self.reply=reply;receipt=self.ask(StructuredContextSession(self.adapter,self.worker))
        self.assertEqual(receipt['fields']['day']['status'],'conflicting');self.assertIsNone(receipt['fields']['day']['answer'])
    def test_invalid_reference_is_not_hidden_by_composition(self):
        self.enroll()
        def reply(task,answer):answer['f0_conditions']['references']=['invented'];return answer
        self.reply=reply;session=StructuredContextSession(self.adapter,self.worker)
        with self.assertRaisesRegex(ValueError,'references'):self.ask(session)
        self.assertEqual(session.last_attempt()['routes'],['full']);self.assertEqual(self.worker.calls,1)
    def test_combined_length_overflow_refuses_instead_of_truncating(self):
        self.enroll()
        def reply(task,answer):answer['f0_value']['answer']='x'*2040;return answer
        self.reply=reply;session=StructuredContextSession(self.adapter,self.worker)
        with self.assertRaisesRegex(ValueError,'Combined field'):self.ask(session)
        self.assertEqual(self.worker.calls,1)
    def test_combined_reference_overflow_refuses(self):
        self.enroll('\n\n'.join(f'ZP21 note {i}.' for i in range(9)))
        def reply(task,answer):
            refs=[p['id'] for p in task['paragraphs']];answer['f0_value']['references']=refs[:5];answer['f0_conditions']['references']=refs[5:];return answer
        self.reply=reply
        with self.assertRaisesRegex(ValueError,'Combined field'):self.ask(StructuredContextSession(self.adapter,self.worker))
    def test_invalid_inputs_consume_request_budget_without_network(self):
        self.enroll();session=StructuredContextSession(self.adapter,self.worker,max_requests=2)
        with self.assertRaises(ValueError):self.ask(session,{'a':'a','b':'b','c':'c'})
        with self.assertRaises(ValueError):self.ask(session,{'a':'x'*1024})
        self.assertEqual(session.last_attempt()['routes'],[])
        with self.assertRaisesRegex(RuntimeError,'request budget'):self.ask(session)
        self.assertEqual(self.worker.calls,0);self.assertEqual(self.seen,[])
    def test_invalid_constructor_limits(self):
        for kwargs in ({'max_requests':True},{'max_requests':65},{'max_paragraphs':0},{'max_source_bytes':True}):
            with self.assertRaises(ValueError):StructuredContextSession(self.adapter,self.worker,**kwargs)
        with self.assertRaises(ValueError):StructuredContextSession(self.adapter,object())
    def test_busy_reentrant_call_and_input_mutation_do_not_corrupt_mapping(self):
        self.enroll();session=StructuredContextSession(self.adapter,self.worker);fields={'day':'Jour de livraison ZP21'}
        def effect():
            fields.clear();fields['evil']='Changed'
            with self.assertRaisesRegex(RuntimeError,'busy'):self.ask(session)
        self.effect=effect;receipt=self.ask(session,fields)
        self.assertEqual(set(receipt['fields']),{'day'});self.assertEqual(session.last_attempt()['request'],1)
    def test_model_budget_is_shared_across_requests(self):
        self.enroll();self.worker.max_calls=1;session=StructuredContextSession(self.adapter,self.worker)
        self.ask(session)
        with self.assertRaisesRegex(RuntimeError,'call budget'):self.ask(session)
        self.assertEqual(self.worker.calls,1);self.assertEqual(session.last_attempt()['routes'],['full'])
    def test_capacity_error_after_attempt_never_retries(self):
        self.enroll();session=StructuredContextSession(self.adapter,self.worker)
        self.effect=lambda:(_ for _ in ()).throw(ValueError(CAPACITY))
        with self.assertRaisesRegex(ValueError,'maximum conservative'):self.ask(session)
        self.assertEqual(self.worker.calls,1);self.assertEqual(session.last_attempt()['routes'],['full'])
    def test_normalized_unknown_references_and_withheld_text_remain_in_slots(self):
        self.enroll()
        def reply(task,answer):
            answer['f0_exceptions']=dict(status='unknown',answer=None,references=[task['paragraphs'][0]['id']])
            answer['f0_value']=dict(status='unknown',answer='nonassertive text',references=[])
            return answer
        self.reply=reply;receipt=self.ask(StructuredContextSession(self.adapter,self.worker))
        self.assertEqual(receipt['slot_withheld_text_fields'],['f0_value'])
        self.assertEqual(receipt['slot_withheld_unknown_references'],{'f0_exceptions':['s0:p0']})
        self.assertIsNone(receipt['fields']['day']['answer'])
if __name__=='__main__':unittest.main()
