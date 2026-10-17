import copy
import hashlib
import unittest
from ocn_core.evidence_coverage import assess_coverage

class CoverageTests(unittest.TestCase):
    sources={'a':'Origin Brest.','b':'Destination Tours.'}
    def row(self,source,field,value=None,status=None,quote=None):
        return dict(source_id=source,field=field,sha256=hashlib.sha256(self.sources[source].encode()).hexdigest(),
                    status=status or ('value' if value is not None else 'absent'),value=value,
                    quote=(quote or self.sources[source]) if value is not None or status=='ambiguous' else None)
    def complete(self):return [self.row('a','origin','Brest'),self.row('b','origin'),self.row('a','destination'),self.row('b','destination','Tours')]
    def test_complementary_sources_supply_distinct_fields(self):
        r=assess_coverage(('origin','destination'),self.sources,self.complete())
        self.assertEqual(r['values'],{'origin':'Brest','destination':'Tours'})
    def test_incomplete_answer_never_releases_partial_values(self):
        rows=self.complete();rows[-1]=self.row('b','destination')
        r=assess_coverage(('origin','destination'),self.sources,rows)
        self.assertFalse(r['ready']);self.assertEqual(r['values'],{})
        self.assertTrue(r['fields']['origin']['ready'])
    def test_ignored_source_blocks_even_when_other_source_has_value(self):
        r=assess_coverage(('origin',),self.sources,[self.row('a','origin','Brest')])
        self.assertFalse(r['ready']);self.assertEqual(r['fields']['origin']['missing_sources'],['b'])
    def test_conflicting_values_block_and_are_preserved(self):
        r=assess_coverage(('city',),self.sources,[self.row('a','city','Brest'),self.row('b','city','Tours')])
        self.assertIn('conflicting_values',r['fields']['city']['reasons'])
        self.assertEqual(len(r['fields']['city']['observations']),2)
    def test_internal_ambiguity_blocks_other_source_agreement(self):
        r=assess_coverage(('city',),self.sources,[self.row('a','city','Brest'),self.row('b','city',status='ambiguous')])
        self.assertIn('ambiguous_evidence',r['fields']['city']['reasons'])
    def test_changed_source_rejects_stale_observation(self):
        with self.assertRaisesRegex(ValueError,'version'):assess_coverage(('origin',),{**self.sources,'a':'Origin Caen.'},[self.row('a','origin','Brest')])
    def test_duplicate_cannot_overwrite_conflict(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):assess_coverage(('city',),self.sources,[self.row('a','city','Brest'),self.row('a','city','Tours')])
    def test_fabricated_quote_rejected(self):
        row=self.row('a','city','Caen');row['quote']='Caen'
        with self.assertRaisesRegex(ValueError,'excerpt'):assess_coverage(('city',),self.sources,[row])
    def test_scope_cannot_be_expanded_by_observation(self):
        with self.assertRaisesRegex(ValueError,'scope'):assess_coverage(('origin',),self.sources,[self.row('a','destination','Brest')])
    def test_order_invariant_and_no_mutation(self):
        rows=self.complete();before=copy.deepcopy(rows)
        a=assess_coverage(('origin','destination'),self.sources,rows)
        b=assess_coverage(('origin','destination'),dict(reversed(list(self.sources.items()))),list(reversed(rows)))
        self.assertEqual(a,b);self.assertEqual(rows,before)
    def test_existing_quote_does_not_prove_value_truth(self):
        r=assess_coverage(('city',),self.sources,[self.row('a','city','Invented'),self.row('b','city')])
        self.assertTrue(r['ready']) # Deliberate boundary: trusted extraction still required.
        self.assertIn('not semantic',r['scope'])
    def test_unknown_status_and_invalid_absence_rejected(self):
        row=self.row('a','city');row['status']='approved'
        with self.assertRaises(ValueError):assess_coverage(('city',),self.sources,[row])
        row=self.row('a','city');row['value']='Brest'
        with self.assertRaises(ValueError):assess_coverage(('city',),self.sources,[row])
if __name__=='__main__':unittest.main()
