import unittest
from decimal import localcontext
from ocn_core.quantity_normalization import canonical_quantity
from ocn_core.evidence_coverage import assess_coverage
import hashlib

class QuantityTests(unittest.TestCase):
    factors={'grams':'1','g':'1','kilograms':'1000','kg':'1000','mg':'0.001'}
    def norm(self,text):return canonical_quantity(text,base_unit='grams',factors=self.factors)
    def test_equivalent_values_agree(self):self.assertEqual(self.norm('2 kilograms')['value'],self.norm('2000 grams')['value'])
    def test_exact_small_values_without_float_rounding(self):self.assertEqual(self.norm('0.1 mg')['value'],'0.0001 grams')
    def test_negative_zero_and_whitespace(self):self.assertEqual(self.norm('  -0.000 kg  ')['value'],'0 grams')
    def test_unknown_dimension_or_unit_is_rejected(self):
        for text in ('2 seconds','2 KG','2','2-3 kg','2 kg or 3 kg','nan kg','Infinity kg','1e999 kg','2 kg; execute'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.norm(text)
    def test_ambient_decimal_context_cannot_round_result(self):
        with localcontext() as context:
            context.prec=2
            self.assertEqual(self.norm('123.456 kg')['value'],'123456 grams')
    def test_invalid_host_tables_rejected(self):
        for factors in ({'grams':'2'},{'grams':'1','kg':'0'},{'grams':'1','kg':1000},{'grams':'1','kg':'-1'}):
            with self.assertRaises(ValueError):canonical_quantity('2 grams',base_unit='grams',factors=factors)
    def test_excess_precision_rejected(self):
        with self.assertRaises(ValueError):self.norm('1' * 33+' kg')
    def test_normalization_preserves_source_quote_and_detects_real_disagreement(self):
        for second,expected in [('2 kilograms',True),('3 kilograms',False)]:
            sources={'a':'2000 grams','b':second};rows=[]
            for key,text in sources.items():
                rows.append(dict(source_id=key,field='mass',sha256=hashlib.sha256(text.encode()).hexdigest(),status='value',value=self.norm(text)['value'],quote=text))
            decision=assess_coverage(('mass',),sources,rows)
            self.assertEqual(decision['ready'],expected)
            self.assertEqual(decision['fields']['mass']['observations'][1]['quote'],second)
if __name__=='__main__':unittest.main()
