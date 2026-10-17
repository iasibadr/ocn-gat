import unittest
from ocn_core.agent_integration import Integration
from ocn_core.local_repair import variations


class VariationTests(unittest.TestCase):
    def integration(self,source):return Integration(source.encode(),'build_synthesizer')

    def test_unicode_columns_and_preserved_other_bytes(self):
        source='def build_synthesizer(model):\n    pré = "é"; return model.strip() # untouched\n'
        variants=variations(self.integration(source))
        self.assertEqual(len(variants),1)
        self.assertEqual(variants[0][1].source.decode(),source.replace('model.strip()','(model)'))

    def test_each_variant_changes_one_call_and_preserves_precedence(self):
        source='def build_synthesizer(model):\n    return model.strip().lower()\n'
        variants=variations(self.integration(source))
        self.assertEqual(len(variants),2)
        self.assertEqual({v.source.decode() for _,v in variants},{source.replace('model.strip()','(model)'),source.replace('model.strip().lower()','(model.strip())')})

    def test_arguments_and_other_methods_not_mutated(self):
        source='def build_synthesizer(model):\n    return model.strip("x").replace("a","b")\n'
        self.assertEqual(variations(self.integration(source)),[])

    def test_budget_overflow_rejected_not_truncated(self):
        source='def build_synthesizer(model):\n    return model.strip().lower()\n'
        with self.assertRaisesRegex(ValueError,'exceeds'):variations(self.integration(source),limit=1)
        with self.assertRaises(ValueError):variations(self.integration(source),limit=True)

if __name__=='__main__':unittest.main()
