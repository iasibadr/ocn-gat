import copy,hashlib,tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.evidence_context_session import EvidenceContextSession

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.text='The deadline is Friday.\n\nNo institution is identified.'
        (self.docs/'a.md').write_text(self.text)
        self.adapter=DocumentAdapter(self.docs,self.root/'pins.json');self.adapter.bind('a','a.md')
        self.fields={'deadline':'Which deadline?'};self.events=[];self.revision='v1'
    def select(self,payload):
        self.events.append('select');return {f:[payload['paragraphs'][0]['id']] for f in payload['fields']}
    def worker(self,payload):
        self.events.append('answer');return {f:dict(status='supported',answer='Friday',references=[payload['paragraphs'][0]['id']]) for f in payload['fields']}
    def session(self,**kwargs):
        return EvidenceContextSession(self.adapter,kwargs.pop('answerer',self.worker),lambda:self.revision,selector=kwargs.pop('selector',self.select),**kwargs)
    def ask(self,s,**kwargs):return s.answer(kwargs.get('question','Deadline?'),kwargs.get('fields',self.fields),kwargs.get('ids',('a',)))

    def test_relocation_reuses_selection_but_not_answer(self):
        s=self.session();a=self.ask(s);(self.docs/'a.md').rename(self.docs/'moved.md');b=self.ask(s)
        self.assertEqual(self.events,['select','answer','answer'])
        self.assertTrue(b['session']['selection_cache_hit']);self.assertEqual(b['sources']['a']['path'],'moved.md')
        self.assertEqual(b['fields'],a['fields']);self.assertFalse(b['semantic_verification'])
        self.assertEqual(b['unknown_scope'],'provided_passages');self.assertFalse(b['action_authorized'])
    def test_question_field_revision_and_document_order_invalidate(self):
        s=self.session(max_callbacks=32)
        self.ask(s);self.ask(s,question='Another question?');self.ask(s,fields={'deadline':'Changed description?'})
        self.revision='v2';self.ask(s)
        (self.docs/'b.md').write_text('Second document.');self.adapter.bind('b','b.md')
        self.ask(s,ids=('a','b'));self.ask(s,ids=('b','a'))
        self.assertEqual(self.events.count('select'),6)
    def test_authorized_new_version_invalidates_selection(self):
        s=self.session();self.ask(s);new='The deadline is Monday.'
        old=self.adapter.bindings()['a']['sha256'];(self.docs/'a.md').write_text(new)
        with self.assertRaises(ValueError):self.ask(s)
        self.assertEqual(len(self.events),2)
        self.adapter.accept_version('a','a.md',expected_current_sha256=old,expected_new_sha256=hashlib.sha256(new.encode()).hexdigest())
        result=self.ask(s);self.assertFalse(result['session']['selection_cache_hit'])
        self.assertEqual(self.events.count('select'),2)
        # Fixture worker still says Friday: references do not establish truth.
        self.assertEqual(result['fields']['deadline']['answer'],'Friday')
        self.assertFalse(result['semantic_verification'])
    def test_source_change_during_selection_stops_before_answer(self):
        def select(payload):(self.docs/'a.md').write_text('Changed');return self.select(payload)
        s=self.session(selector=select)
        with self.assertRaises(ValueError):self.ask(s)
        self.assertEqual(self.events,['select'])
    def test_change_in_unselected_source_during_answer_blocks_output(self):
        (self.docs/'b.md').write_text('Unselected.');self.adapter.bind('b','b.md')
        def worker(payload):(self.docs/'b.md').write_text('Changed');return self.worker(payload)
        with self.assertRaises(ValueError):self.ask(self.session(answerer=worker),ids=('a','b'))
    def test_budget_reserves_complete_request_and_failures_are_charged(self):
        with self.assertRaises(RuntimeError):self.ask(self.session(max_callbacks=1))
        self.assertEqual(self.events,[])
        def fail(payload):self.events.append('failed');raise RuntimeError('offline')
        s=self.session(answerer=fail,max_callbacks=3)
        with self.assertRaisesRegex(RuntimeError,'offline'):self.ask(s)
        with self.assertRaisesRegex(RuntimeError,'Insufficient'):self.ask(s)
        self.assertEqual(self.events,['select','failed'])
    def test_cache_capacity_and_zero_capacity(self):
        s=self.session(cache_capacity=1,max_callbacks=10)
        self.ask(s);r=self.ask(s,question='Other?');self.assertEqual(r['session']['selection_cache_evictions'],1)
        self.assertFalse(self.ask(s)['session']['selection_cache_hit'])
        z=self.session(cache_capacity=0);self.ask(z);r=self.ask(z)
        self.assertFalse(r['session']['selection_cache_hit']);self.assertEqual(r['session']['selection_cache_entries'],0)
    def test_no_selector_is_full_context_one_callback(self):
        s=self.session(selector=None);r=self.ask(s)
        self.assertEqual(len(r['evidence']),2);self.assertEqual(r['session']['callback_invocations'],1)
        self.assertIsNone(r['selection'])
    def test_nonassertions_withhold_text_without_bypassing_references(self):
        def unknown(p):return {'deadline':dict(status='unknown',answer='Unsupported text',references=[])}
        r=self.ask(self.session(answerer=unknown));self.assertIsNone(r['fields']['deadline']['answer'])
        self.assertEqual(r['withheld_text_fields'],['deadline'])
        def conflict(p):return {'deadline':dict(status='conflicting',answer='Description',references=[x['id'] for x in p['paragraphs']])}
        r=self.ask(self.session(selector=None,answerer=conflict));self.assertIsNone(r['fields']['deadline']['answer'])
        with self.assertRaises(ValueError):self.ask(self.session(answerer=conflict))
    def test_unknown_references_or_missing_fields_do_not_populate_cache(self):
        for bad in ({}, {'deadline':dict(status='supported',answer='Friday',references=['outside'])}):
            s=self.session(answerer=lambda p:copy.deepcopy(bad))
            with self.assertRaises(ValueError):self.ask(s)
            with self.assertRaises(ValueError):self.ask(s)
        self.assertEqual(self.events.count('select'),4)
    def test_invalid_selection_and_resource_bounds_before_worker(self):
        for selector in [lambda p:{},lambda p:{'deadline':['s0:p99']},lambda p:{'deadline':['s0:p0','s0:p0']}]:
            with self.assertRaises(ValueError):self.ask(self.session(selector=selector))
        for kw in [dict(max_source_bytes=1),dict(max_paragraphs=1)]:
            with self.assertRaises(ValueError):self.ask(self.session(**kw))
        self.assertEqual(self.events,[])
    def test_mutation_reentrance_and_policy_change_fail_safely(self):
        def worker(payload):
            with self.assertRaises(RuntimeError):self.ask(s)
            payload['paragraphs'][0]['text']='Injected'
            return self.worker(payload)
        s=self.session(answerer=worker);r=self.ask(s)
        self.assertEqual(r['evidence']['s0:p0']['text'],'The deadline is Friday.')
        r['selection']['deadline'].clear();self.assertTrue(self.ask(s)['session']['selection_cache_hit'])
        def change(payload):self.revision='v3';return self.worker(payload)
        with self.assertRaisesRegex(ValueError,'Policy changed'):self.ask(self.session(answerer=change))
    def test_request_limit_and_invalid_types(self):
        s=self.session(max_requests=1)
        with self.assertRaises(ValueError):self.ask(s,fields={})
        with self.assertRaises(RuntimeError):self.ask(s)
        for kwargs in [dict(cache_capacity=True),dict(max_callbacks=0),dict(max_paragraphs=0)]:
            with self.assertRaises(ValueError):self.session(**kwargs)

if __name__=='__main__':unittest.main()
