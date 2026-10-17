import copy,tempfile,unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from ocn_core.lexical_context import LexicalContextSelector
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.evidence_context_session import EvidenceContextSession

def request(texts,question='Quelle date pour LT73 ?'):
    return dict(question=question,fields={'date':'Date et conditions'},paragraphs=[
        dict(id=str(i),document_id=doc,start=0,end=len(text),text=text)
        for i,(doc,text) in enumerate(texts)])

class LexicalTests(unittest.TestCase):
    def test_diverse_sources_retain_complement(self):
        r=request([('a','Date LT73 fixée au 22 avril.'),('a','Date LT73 au calendrier.'),
            ('a','Date LT73 annoncée.'),('a','Date LT73 publiée.'),('b','LT73 nécessite un visa douanier.')])
        self.assertNotIn('4',LexicalContextSelector()(r)['date'])
        self.assertIn('4',LexicalContextSelector(True)(r)['date'])
        self.assertEqual(len(LexicalContextSelector(True)(r)['date']),4)

    def test_no_anchor_fallback_empty_and_no_overlap(self):
        r=request([('a','La date est lundi.'),('b','Les frais sont élevés.')],question='Quelle date ?')
        self.assertEqual(LexicalContextSelector()(r),LexicalContextSelector(True)(r))
        self.assertEqual(LexicalContextSelector()(request([])),{'date':[]})
        self.assertEqual(LexicalContextSelector()(request([('a','Banane orange')])),{'date':[]})

    def test_exact_duplicates_do_not_displace_complement(self):
        r=request([(str(i),'Date LT73 fixée au 22 avril.') for i in range(4)]+
            [('other','LT73 nécessite un visa douanier.')])
        original=copy.deepcopy(r)
        self.assertNotIn('4',LexicalContextSelector(True)(r)['date'])
        self.assertEqual(set(LexicalContextSelector(True,True)(r)['date']),{'0','4'})
        self.assertEqual(r,original)
        self.assertNotEqual(LexicalContextSelector(True).revision(),LexicalContextSelector(True,True).revision())
        with self.assertRaises(ValueError):LexicalContextSelector(deduplicate=1)

    def test_negation_and_whitespace_are_not_duplicate_text(self):
        r=request([('a','LT73 autorisé.'),('b','LT73 non autorisé.'),
            ('c','LT73 autorisé. '),('d','LT73 autorisé.')])
        self.assertEqual(set(LexicalContextSelector(True,True)(r)['date']),{'0','1','2'})

    def test_configuration_and_catalog_validation(self):
        with self.assertRaises(ValueError):LexicalContextSelector(1)
        selector=LexicalContextSelector()
        with self.assertRaises(FrozenInstanceError):selector.entity_coverage=True
        self.assertNotEqual(selector.revision(),LexicalContextSelector(True).revision())
        r=request([('a','Date lundi.')]);r['paragraphs'].append(copy.deepcopy(r['paragraphs'][0]))
        with self.assertRaises(ValueError):selector(r)
        r=request([('a','Date lundi.')]);r['paragraphs'][0]['end']=500
        with self.assertRaises(ValueError):selector(r)
        r=request([('a','x'*262145)])
        with self.assertRaises(ValueError):selector(r)

    def test_session_relocation_and_changed_content_reselect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docs=root/'docs';docs.mkdir();file=docs/'a.md'
            file.write_text('LT73 livraison lundi.')
            adapter=DocumentAdapter(docs,root/'pins.json');adapter.bind('a','a.md')
            selector=LexicalContextSelector(True);seen=[]
            def answer(r):
                seen.append(r['paragraphs'][0]['text'])
                return {'date':dict(status='supported',answer=seen[-1],references=[r['paragraphs'][0]['id']])}
            s=EvidenceContextSession(adapter,answer,selector.revision,selector=selector,max_callbacks=5)
            ask=lambda:s.answer('Date de livraison LT73 ?',{'date':'Date'},('a',))
            initial=ask();file.rename(docs/'b.md');self.assertTrue(ask()['session']['selection_cache_hit'])
            (docs/'b.md').write_text('LT73 livraison mardi.')
            with self.assertRaises(ValueError):ask()
            import hashlib
            adapter.accept_version('a','b.md',expected_current_sha256=initial['sources']['a']['sha256'],
                expected_new_sha256=hashlib.sha256((docs/'b.md').read_bytes()).hexdigest())
            result=ask();self.assertFalse(result['session']['selection_cache_hit'])
            self.assertEqual(seen,['LT73 livraison lundi.','LT73 livraison lundi.','LT73 livraison mardi.'])

    def test_cli_local_selection_charges_only_one_model_call(self):
        import importlib.util,io,json
        from contextlib import redirect_stdout
        from unittest.mock import patch
        path=Path(__file__).resolve().parents[1]/'examples/local_evidence_context.py'
        spec=importlib.util.spec_from_file_location('lexical_cli_test',path)
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        class Worker:
            def __init__(self,model,max_calls):
                self.max_calls=max_calls;self.calls=0
            def revision(self):return 'fixture-worker-v1'
            def attempts(self):return [dict(stage='answer')]*self.calls
            def select(self,r):raise AssertionError('No model selection allowed')
            def answer(self,r):
                self.calls+=1
                assert self.calls<=self.max_calls==1
                return {'date':dict(status='supported',answer='lundi',references=[r['paragraphs'][0]['id']])}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'a.md').write_text('LT73 livraison lundi.')
            for mode in ('bm25','coverage','unique-coverage'):
                out=io.StringIO()
                argv=['example','--model','fixture','--habitat',tmp,'--document','a=a.md',
                    '--field','date=Date','--question','Livraison LT73 ?','--lexical-context',mode]
                with patch.object(cli,'LocalEvidenceContextWorker',Worker),patch('sys.argv',argv),redirect_stdout(out):
                    self.assertEqual(cli.main(),0)
                result=json.loads(out.getvalue())
                self.assertEqual(len(result['model_attempts']),1)
                self.assertEqual(result['receipt']['session']['callback_invocations'],2)
                self.assertIn('ocn.lexical-context.v1',result['receipt']['policy_revision'])

if __name__=='__main__':unittest.main()
