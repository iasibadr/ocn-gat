import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.adaptive_context_session import AdaptiveContextSession
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.local_evidence_context import LocalEvidenceContextWorker

CAPACITY='Prompt exceeds maximum conservative context allowance'
class BudgetedSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.docs=self.root/'docs';self.docs.mkdir()
        self.adapter=DocumentAdapter(self.docs,self.root/'state.json')
        patcher=patch('ocn_core.local_evidence_context.require_model',return_value={'digest':'fixed'})
        patcher.start();self.addCleanup(patcher.stop)
        self.worker=LocalEvidenceContextWorker('fixture',max_calls=3)
        self.limit=500;self.answers=0
        def preflight(payload):
            if sum(len(p['text']) for p in payload['paragraphs'])>self.limit:raise ValueError(CAPACITY)
            return {}
        self.worker.context_plan=preflight
        def answer(payload):
            preflight(payload)
            self.answers+=1;self.worker._attempts.append({'stage':'answer'})
            return {'conditions':dict(status='supported',answer='; '.join(p['text'] for p in payload['paragraphs']),references=[p['id'] for p in payload['paragraphs']])}
        self.worker.answer=answer
        for i in range(5):
            (self.docs/f'{i}.md').write_text(f'ZX42 condition {i}.\n\n'+'Archives décoratives. '*30)
            self.adapter.bind(str(i),f'{i}.md')
        self.session=AdaptiveContextSession(self.adapter,self.worker,selection='budgeted')
    def ask(self):return self.session.answer('Conditions ZX42?',{'conditions':'Toutes les conditions'},tuple(str(i) for i in range(5)))

    def test_all_five_survive_with_exclusions_visible(self):
        r=self.ask();self.assertEqual(len(r['selection']['conditions']),5)
        self.assertEqual(r['context_routing']['routes'],['full','budgeted-coverage'])
        coverage=r['context_routing']['coverage']
        self.assertEqual(len(coverage['excluded_zero_overlap']),1) # four exact noise copies deduplicated
        self.assertEqual(len(coverage['duplicate_of']),4)
        self.assertFalse(coverage['semantic_completeness'])
        self.assertEqual(self.worker.calls,1)

    def test_relocation_and_no_stale_plan_cache(self):
        self.ask();(self.docs/'4.md').rename(self.docs/'moved.md');r=self.ask()
        self.assertEqual(r['sources']['4']['path'],'moved.md')
        self.assertFalse(r['session']['selection_cache_hit']);self.assertEqual(self.worker.calls,2)

    def test_changed_source_rejected_before_next_answer(self):
        self.ask();(self.docs/'4.md').write_text('New facts')
        with self.assertRaisesRegex(ValueError,'Enrolled version unavailable'):self.ask()
        self.assertEqual(self.answers,1)

    def test_change_in_unselected_content_during_plan_blocks_answer(self):
        probe=self.worker.context_plan
        def mutate(payload):
            (self.docs/'4.md').write_text('Changed during capacity calculation')
            return probe(payload)
        self.worker.context_plan=mutate
        with self.assertRaisesRegex(ValueError,'Source version|Enrolled version'):self.ask()
        self.assertEqual(self.answers,0)

    def test_candidate_overflow_refuses_and_reports_deferred(self):
        self.limit=30
        with self.assertRaisesRegex(ValueError,'batching required'):self.ask()
        r=self.session.last_attempt()
        self.assertEqual(r['status'],'failed');self.assertTrue(r['coverage']['deferred'])
        self.assertEqual(self.answers,0)

    def test_oversized_candidate_refuses_before_inference(self):
        self.limit=2
        with self.assertRaisesRegex(ValueError,'batching required'):self.ask()
        self.assertEqual(len(self.session.last_attempt()['coverage']['oversized']),5)
        self.assertEqual(self.answers,0)

    def test_non_capacity_preflight_errors_not_swallowed(self):
        def bad(payload):raise ValueError('Unexpected shape')
        self.worker.context_plan=bad
        with self.assertRaisesRegex(ValueError,'Unexpected shape'):self.ask()
        self.assertEqual(self.answers,0)

    def test_full_route_has_no_previous_coverage(self):
        self.ask();self.limit=10000
        # Short fake answer avoids the fixture's answer-length bound.
        def answer(payload):
            return {'conditions':dict(status='supported',answer='fixture',references=['s0:p0'])}
        self.worker.answer=answer
        r=self.ask();self.assertEqual(r['context_routing']['routes'],['full'])
        self.assertNotIn('coverage',r['context_routing'])

if __name__=='__main__':unittest.main()
