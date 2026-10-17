import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.adaptive_context_session import AdaptiveContextSession
from ocn_core.evidence_context_session import EvidenceContextSession
from ocn_core.local_evidence_context import LocalEvidenceContextWorker
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.source_windows import split_passage

class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.text='Préambule. Condition ZX42 : certificat obligatoire. Cette obligation ne concerne pas les majeurs. '+('Inventaire décoratif. '*30)
        (self.docs/'a.md').write_text(self.text)
        self.adapter=DocumentAdapter(self.docs,self.root/'state.json');self.adapter.bind('a','a.md')
        pin=patch('ocn_core.local_evidence_context.require_model',return_value={'digest':'fixed'});pin.start();self.addCleanup(pin.stop)
        self.worker=LocalEvidenceContextWorker('fixture',max_calls=4);self.payloads=[]
        def capacity(payload):
            if sum(len(p['text']) for p in payload['paragraphs'])>200:
                raise ValueError('Prompt exceeds maximum conservative context allowance')
            return {}
        self.worker.context_plan=capacity
        def answer(payload):
            capacity(payload);self.payloads.append(payload);self.worker._attempts.append({'stage':'answer'})
            return {'fact':dict(status='supported',answer='certificat sauf majeurs',references=[payload['paragraphs'][-1]['id']])}
        self.worker.answer=answer
    def ask(self,session):return session.answer('Condition ZX42 ?',{'fact':'Condition ZX42'},('a',))
    def session(self,**kw):return AdaptiveContextSession(self.adapter,self.worker,selection='source-windows',**kw)
    def evidence(self,response,**kw):return EvidenceContextSession(self.adapter,lambda p:response,lambda:'policy',**kw)
    def test_exact_spans_and_neighbor_in_receipt(self):
        r=self.ask(self.session());self.assertEqual(r['context_routing']['routes'],['full','source-windows'])
        self.assertEqual(r['passage_mode'],'sentence');self.assertEqual(self.worker.calls,1)
        self.assertIn('ne concerne pas les majeurs',''.join(p['text'] for p in r['evidence'].values()))
        for p in r['evidence'].values():self.assertEqual(self.text[p['start']:p['end']],p['text'])
        self.assertEqual(list(r['evidence']),[p['id'] for p in self.payloads[0]['paragraphs']])
    def test_relocation_retains_valid_spans(self):
        s=self.session();a=self.ask(s);(self.docs/'a.md').rename(self.docs/'moved.md');b=self.ask(s)
        self.assertEqual(a['evidence'],b['evidence']);self.assertEqual(b['sources']['a']['path'],'moved.md')
        self.assertFalse(b['session']['selection_cache_hit'])
    def test_version_change_during_selection_stops_before_answer(self):
        original=self.worker.context_plan
        def changed(payload):
            result=original(payload)
            (self.docs/'a.md').write_text('Changed')
            return result
        self.worker.context_plan=changed
        with self.assertRaisesRegex(ValueError,'Enrolled version'):self.ask(self.session())
        self.assertEqual(self.worker.calls,0)
    def test_unknown_null_is_normalized_with_validated_trace(self):
        value={'fact':dict(status='unknown',answer=None,references=['s0:p0'])}
        r=self.ask(self.evidence(value,normalize_unknown_references=True))
        self.assertEqual(r['fields']['fact']['references'],[])
        self.assertEqual(r['withheld_unknown_references'],{'fact':['s0:p0']})
        self.assertIsNone(r['fields']['fact']['answer'])
    def test_unknown_bad_reference_is_not_normalized(self):
        value={'fact':dict(status='unknown',answer=None,references=['invented'])}
        with self.assertRaisesRegex(ValueError,'references'):
            self.ask(self.evidence(value,normalize_unknown_references=True))
    def test_unknown_text_with_references_is_not_normalized(self):
        value={'fact':dict(status='unknown',answer='unsupported assertion',references=['s0:p0'])}
        with self.assertRaisesRegex(ValueError,'Unknown cannot'):
            self.ask(self.evidence(value,normalize_unknown_references=True))
    def test_default_still_rejects_unknown_references(self):
        value={'fact':dict(status='unknown',answer=None,references=['s0:p0'])}
        with self.assertRaisesRegex(ValueError,'Unknown cannot'):self.ask(self.evidence(value))
    def test_chunk_expansion_limit_precedes_answer(self):
        with self.assertRaisesRegex(ValueError,'Paragraph budget'):self.ask(self.session(max_paragraphs=3))
        self.assertEqual(self.worker.calls,0)
    def test_selected_window_overflow_not_truncated(self):
        (self.docs/'b.md').write_text('Condition ZX42 '+'x'*500);self.adapter.bind('b','b.md')
        s=self.session()
        with self.assertRaisesRegex(ValueError,'conservative context'):s.answer('Condition ZX42',{'fact':'Condition'},('b',))
        self.assertFalse(s.last_attempt()['coverage']['fits']);self.assertEqual(self.worker.calls,0)
    def test_unselected_reference_is_invalid(self):
        original=self.worker.answer
        def wrong(payload):
            value=original(payload);value['fact']['references']=['s0:p0:c20'];return value
        self.worker.answer=wrong
        with self.assertRaisesRegex(ValueError,'references'):self.ask(self.session())
    def test_unicode_decimal_roundtrip(self):
        text='Montant 3.5 euros. Échéance demain! Autre phrase.'
        p=dict(id='s0:p0',document_id='d',start=9,end=9+len(text),text=text)
        values=list(split_passage(p));self.assertEqual(''.join(x['text'] for x in values),text)
        self.assertIn('3.5',values[0]['text'])
        for x in values:self.assertEqual(text[x['start']-9:x['end']-9],x['text'])
    def test_constructor_validation(self):
        with self.assertRaises(ValueError):self.evidence({},passage_mode='guess')
        with self.assertRaises(ValueError):self.evidence({},normalize_unknown_references=1)

if __name__=='__main__':unittest.main()
