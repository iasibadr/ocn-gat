import unittest
from ocn_core.grounded_temporal import assess_extraction,extraction_schema

class GroundedTemporalTests(unittest.TestCase):
    def assess(self,items,*,known='2026-01-03T00:00:00Z',effective='2026-01-03T00:00:00Z'):
        sources={str(i):dict(text=item['quote'],observed_at='2026-01-02T00:00:00Z') for i,item in enumerate(items)}
        items=[dict(item,source_id=str(i)) for i,item in enumerate(items)]
        return assess_extraction({'statements':items},sources,subject='shoes',predicate='location',known_at=known,effective_at=effective)

    def item(self,quote,value='drawer',polarity='affirmed',date='2026-01-01'):
        return dict(quote=quote,value=value,polarity=polarity,date_quote=date)

    def test_ungrounded_date_is_rejected_not_observation_imputed(self):
        with self.assertRaisesRegex(ValueError,'quoted explicitly'):
            self.assess([self.item('The shoes are in the drawer.')])
        unknown=self.assess([self.item('The shoes are in the drawer.',date=None)])
        self.assertEqual(unknown['status'],'unresolved_time')
        with self.assertRaises(ValueError):self.assess([self.item('On 2026-02-30 in drawer.',date='2026-02-30')])

    def test_negation_invalidates_same_value_without_inventing_replacement(self):
        old=self.item('On 2026-01-01 shoes are in drawer.')
        negative=self.item('On 2026-01-02 shoes are not in drawer.',polarity='negated',date='2026-01-02')
        result=self.assess([old,negative])
        self.assertEqual(result['status'],'negated_without_replacement');self.assertIsNone(result['value'])
        self.assertEqual(self.assess([old,negative],effective='2026-01-01T12:00:00Z')['value'],'drawer')

    def test_other_location_negation_and_hypothesis_do_not_replace_state(self):
        old=self.item('On 2026-01-01 shoes are in drawer.')
        negative=self.item('On 2026-01-02 shoes are not in locker.',value='locker',polarity='negated',date='2026-01-02')
        hypothetical=self.item('On 2026-01-02 shoes might be in hall.',value='hall',polarity='hypothetical',date='2026-01-02')
        result=self.assess([old,negative,hypothetical])
        self.assertEqual(result['value'],'drawer');self.assertFalse(result['semantic_verification'])
        self.assertEqual(len(result['extraction_audit']),3)

    def test_uncertain_or_undated_negative_requires_no_final_value(self):
        old=self.item('On 2026-01-01 shoes are in drawer.')
        uncertain=self.item('Shoes might be in locker.',value='locker',polarity='uncertain',date=None)
        self.assertEqual(self.assess([old,uncertain])['status'],'unresolved_polarity')
        negative=self.item('Shoes are not in drawer.',polarity='negated',date=None)
        self.assertEqual(self.assess([old,negative])['status'],'negated_without_replacement')
        self.assertEqual(self.assess([old,uncertain],known='2026-01-01T00:00:00Z')['status'],'missing')

    def test_schema_and_fields_are_bounded(self):
        self.assertEqual(extraction_schema(['s'])['properties']['statements']['maxItems'],64)
        for ids in ([],['s','s'],['s']*17):
            with self.assertRaises(ValueError):extraction_schema(ids)
        with self.assertRaises(ValueError):self.assess([self.item('On 2026-01-01 in drawer.',polarity='fact')])

if __name__=='__main__':unittest.main()
