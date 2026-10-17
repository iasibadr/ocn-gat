import unittest
from ocn_core.budgeted_evidence import plan


def request(n, *, size=40):
    return dict(question='conditions ZX42',fields={'conditions':'conditions'},paragraphs=[
        dict(id=f'p{i}',document_id=f'd{i}',start=0,end=len(text),text=text)
        for i in range(n) for text in [f'condition ZX42 numero {i} '+('a'*size)]])


class PlannerTests(unittest.TestCase):
    def test_five_and_eight_not_capped_at_four(self):
        for n in (5,8):
            r=plan(request(n),lambda p:len(p['paragraphs'])<=8)
            self.assertEqual(r['batches'],[[f'p{i}' for i in range(n)]])
            self.assertTrue(r['all_candidates_packed'])
            self.assertFalse(r['semantic_completeness'])

    def test_multibatch_and_budget_accounting(self):
        r=plan(request(11),lambda p:len(p['paragraphs'])<=3,max_batches=3)
        self.assertEqual(list(map(len,r['batches'])),[3,3,3])
        self.assertEqual(r['deferred'],['p9','p10'])
        self.assertFalse(r['all_candidates_packed'])
        self.assertEqual(r['model_calls'],0)

    def test_oversized_evidence_is_visible(self):
        q=request(2); q['paragraphs'][0]['text']+='x'*200
        q['paragraphs'][0]['end']=len(q['paragraphs'][0]['text'])
        r=plan(q,lambda p:sum(len(x['text']) for x in p['paragraphs'])<=100)
        self.assertEqual(r['oversized'],['p0'])
        self.assertEqual(r['batches'],[['p1']])

    def test_exact_duplicates_only_and_unmatched_reported(self):
        q=request(2)
        q['paragraphs'] += [dict(q['paragraphs'][0],id='copy',document_id='copy'),
            dict(id='other',document_id='other',start=0,end=5,text='bruit')]
        r=plan(q,lambda p:True)
        self.assertEqual(r['duplicate_of'],{'copy':'p0'})
        self.assertEqual(r['excluded_zero_overlap'],['other'])
        self.assertEqual(len(r['batches'][0]),2)

    def test_fairness_across_sources(self):
        q=request(6)
        for p in q['paragraphs'][:5]:p['document_id']='large'
        r=plan(q,lambda p:len(p['paragraphs'])<=2,max_batches=1)
        self.assertEqual(r['batches'][0],['p0','p5'])

    def test_capacity_contract_and_limits(self):
        with self.assertRaises(ValueError):plan(request(1),lambda p:False)
        with self.assertRaises(ValueError):plan(request(1),lambda p:1)
        with self.assertRaises(ValueError):plan(request(1),lambda p:True,max_batches=True)

    def test_no_input_mutation(self):
        q=request(2)
        import copy
        before=copy.deepcopy(q)
        def mutating(p):
            p['paragraphs'].clear();p['fields'].clear();return True
        # Predicate receives an isolated payload, including question fields.
        plan(q,mutating)
        self.assertEqual(q,before)

if __name__=='__main__':unittest.main()
