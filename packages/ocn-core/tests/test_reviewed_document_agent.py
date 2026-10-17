import tempfile,unittest
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.reviewed_document_agent import ReviewedDocumentAgent


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.docs=root/'docs';self.docs.mkdir()
        self.text='La rencontre est à Oujda. Samira est responsable.'
        (self.docs/'a.txt').write_text(self.text)
        self.adapter=DocumentAdapter(self.docs,root/'pins.json');self.adapter.bind('a','a.txt')

    def producer(self,q,docs):
        return dict(response=dict(answer='À Paris avec Karim.',abstain=False,
            citations=[dict(document_id='a',quote=self.text)]),usage={})

    def gate(self,reviewer,**kwargs):
        return ReviewedDocumentAgent(self.adapter,self.producer,reviewer,reviewer_id='test-reviewer-v1',**kwargs)

    def verdict(self,status):
        return dict(verdict=status,reason='Les noms et le lieu doivent correspondre au document.',
            evidence=[dict(document_id='a',quote=self.text)])

    def test_wrong_answer_with_exact_citation_is_withheld(self):
        for status in ('rejected','uncertain'):
            result=self.gate(lambda *a:self.verdict(status)).answer('Où et qui ?',('a',))
            self.assertEqual(result['answer'],'');self.assertEqual(result['citations'],[])
            self.assertFalse(result['approved_for_use']);self.assertTrue(result['abstain'])
            self.assertEqual(result['callback_invocations_total'],2)

    def test_accepted_judgment_is_attributed_not_a_truth_guarantee(self):
        # A bad reviewer can accept a false candidate: the API must not call that proof.
        result=self.gate(lambda *a:self.verdict('accepted')).answer('Où et qui ?',('a',))
        self.assertTrue(result['approved_for_use'])
        self.assertIn('not formal truth proof',result['semantic_review']['scope'])
        self.assertEqual(result['semantic_review']['reviewer_id'],'test-reviewer-v1')

    def test_bad_review_and_invented_evidence_fail_closed(self):
        invalid=[True,dict(verdict='yes',reason='x',evidence=[]),
            dict(verdict='accepted',reason='ok',evidence=[]),
            dict(verdict='accepted',reason='ok',evidence=[dict(document_id='a',quote='Invented')])]
        for verdict in invalid:
            with self.assertRaises(ValueError):self.gate(lambda *a:verdict).answer('Où ?',('a',))

    def test_source_mutation_during_review_blocks_answer(self):
        def reviewer(*args):
            (self.docs/'a.txt').write_text('La rencontre est à Paris.')
            return self.verdict('accepted')
        with self.assertRaises(ValueError):self.gate(reviewer).answer('Où ?',('a',))

    def test_review_cannot_modify_candidate_or_source_snapshot(self):
        def reviewer(q,documents,candidate):
            documents[0]['text']='Rewritten';candidate['answer']='Injected'
            return self.verdict('accepted')
        result=self.gate(reviewer).answer('Où ?',('a',))
        self.assertEqual(result['answer'],'À Paris avec Karim.')

    def test_failure_is_charged_and_no_synthesis_when_review_unaffordable(self):
        def failed(*a):raise RuntimeError('review unavailable')
        agent=self.gate(failed,max_calls=3)
        with self.assertRaisesRegex(RuntimeError,'unavailable'):agent.answer('Où ?',('a',))
        self.assertEqual(agent.calls,2)
        with self.assertRaisesRegex(RuntimeError,'Two callback'):agent.answer('Où ?',('a',))
        self.assertEqual(agent.calls,2)

    def test_full_context_is_sent_and_reentrant_call_rejected(self):
        (self.docs/'b.txt').write_text('Une contradiction supplémentaire.')
        self.adapter.bind('b','b.txt')
        def reviewer(q,documents,candidate):
            self.assertEqual({d['document_id'] for d in documents},{'a','b'})
            with self.assertRaisesRegex(RuntimeError,'busy'):agent.answer('Où ?',('a',))
            return self.verdict('uncertain')
        agent=self.gate(reviewer)
        self.assertFalse(agent.answer('Où ?',('a','b'))['approved_for_use'])


if __name__=='__main__':unittest.main()
