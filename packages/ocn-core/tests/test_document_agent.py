from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_agent import DocumentAgent

class DocumentAgentTests(unittest.TestCase):
    def fixture(self,root):
        h=root/'h';h.mkdir();(h/'a.txt').write_text('Delivery Friday.');(h/'b.txt').write_text('Owner Maya.')
        adapter=DocumentAdapter(h,root/'state.json');adapter.bind('a','a.txt');adapter.bind('b','b.txt')
        return h,adapter
    def response(self):return dict(response=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')]),usage={})
    def test_existing_synthesizer_unchanged_after_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp));synth=Mock(return_value=self.response());agent=DocumentAgent(a,synth)
            (h/'a.txt').rename(h/'moved.txt')
            result=agent.answer('When?',('a','b'))
            self.assertEqual(result['citations'][0]['path'],'moved.txt');synth.assert_called_once()
            self.assertEqual(synth.call_args.args[0],'When?')
    def test_relocation_during_synthesis_uses_verified_utf8_size_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h,a=self.fixture(root)
            # Multibyte content distinguishes byte length from character count.
            (h/'unicode.md').write_text('Livraison prévue vendredi.',encoding='utf-8')
            a.bind('unicode','unicode.md');size=len('Livraison prévue vendredi.'.encode('utf-8'))
            def synth(q,docs):
                (h/'unicode.md').rename(h/'moved.md')
                (h/'unrelated.md').write_text('x'*70000)
                return dict(response=dict(answer='vendredi',abstain=False,
                    citations=[dict(document_id='unicode',quote='vendredi')]),usage={})
            result=DocumentAgent(a,synth).answer('Quand?',('unicode',))
            self.assertEqual(result['citations'][0]['path'],'moved.md')
            self.assertEqual(result['document_bytes_read'],3*size)
            restored=DocumentAdapter(h,root/'state.json')
            self.assertEqual(restored.read('unicode').entries_scanned,0)

    def test_relocation_during_synthesis_still_rejects_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp));before=a.state.read_bytes()
            def synth(q,docs):
                (h/'a.txt').rename(h/'moved.txt')
                (h/'duplicate.txt').write_bytes((h/'moved.txt').read_bytes())
                return self.response()
            with self.assertRaisesRegex(ValueError,'Ambiguous'):
                DocumentAgent(a,synth).answer('When?',('a',))
            self.assertEqual(a.state.read_bytes(),before)

    def test_budget_prevents_call_and_unknown_document_cannot_be_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp));synth=Mock();agent=DocumentAgent(a,synth,max_context_bytes=1)
            with self.assertRaises(ValueError):agent.answer('When?',('a',))
            synth.assert_not_called()
            with self.assertRaises(ValueError):agent.answer('When?',('unknown',))
    def test_uncited_changed_document_rejects_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp))
            def synth(q,docs):(h/'b.txt').write_text('Owner changed.');return self.response()
            with self.assertRaises(ValueError):DocumentAgent(a,synth).answer('When?',('a','b'))
    def test_unknown_or_fabricated_citation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp))
            for ident,quote in [('unknown','Friday'),('a','Monday')]:
                response=self.response();response['response']['citations']=[dict(document_id=ident,quote=quote)]
                with self.assertRaises(ValueError):DocumentAgent(a,lambda q,d:response).answer('When?',('a',))
    def test_local_constructor_uses_same_validation_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp))
            with patch('ocn_core.document_agent.LocalDocumentSynthesizer.__call__',return_value=self.response()) as call:
                result=DocumentAgent.from_local_model(a).answer('When?',('a',))
                self.assertEqual(result['answer'],'Friday');call.assert_called_once()
    def test_abstention_is_not_an_answer_and_quote_is_not_semantic_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            h,a=self.fixture(Path(tmp));response=self.response();response['response']['answer']='Monday'
            result=DocumentAgent(a,lambda q,d:response).answer('When?',('a',))
            self.assertEqual(result['answer'],'Monday') # Exact quote checks cannot establish claim truth.
            response['response']=dict(answer='Unknown',abstain=True,citations=[])
            self.assertTrue(DocumentAgent(a,lambda q,d:response).answer('When?',('a',))['abstain'])

    def test_empty_abstention_is_valid_but_empty_assertion_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,a=self.fixture(Path(tmp))
            response=dict(response=dict(answer='',abstain=True,citations=[]),usage={})
            result=DocumentAgent(a,lambda q,d:response).answer('When?',('a',))
            self.assertTrue(result['abstain']);self.assertEqual(result['answer'],'')
            response['response']['abstain']=False
            response['response']['citations']=[dict(document_id='a',quote='Friday')]
            with self.assertRaises(ValueError):DocumentAgent(a,lambda q,d:response).answer('When?',('a',))
            response['response']['abstain']=True
            with self.assertRaises(ValueError):DocumentAgent(a,lambda q,d:response).answer('When?',('a',))

if __name__=='__main__':unittest.main()
