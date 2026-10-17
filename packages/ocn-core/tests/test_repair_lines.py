import unittest
from ocn_core.bridge_repair import decode_proposal,LocalBridgeRepairer
from ocn_core.agent_integration import Integration


class LinesTests(unittest.TestCase):
    def test_preserves_indentation_and_literal_string_escapes(self):
        lines=['def build_synthesizer(model):','    text = "line1\\nline2"','    return None']
        source=decode_proposal(dict(diagnosis='Example',lines=lines),'lines')
        self.assertEqual(source,'\n'.join(lines)+'\n')
        Integration(source.encode(),'build_synthesizer').descriptor()

    def test_multiline_elements_or_extra_fields_rejected(self):
        for value in [dict(diagnosis='x',lines=['a\nb']),dict(diagnosis='x',lines=['a\rb']),
            dict(diagnosis='',lines=['a']),dict(diagnosis='x',lines=[]),dict(diagnosis='x',lines=[1]),
            dict(diagnosis='x',lines=['a'],command='run')]:
            with self.assertRaises(ValueError):decode_proposal(value,'lines')

    def test_no_heuristic_decoding_or_format_fallback(self):
        literal='def build_synthesizer(model):\\n    return None'
        self.assertEqual(decode_proposal({'source':literal},'source'),literal)
        with self.assertRaises(ValueError):Integration(literal.encode(),'build_synthesizer').descriptor()
        with self.assertRaises(ValueError):decode_proposal({'source':'x'},'lines')
        with self.assertRaises(ValueError):LocalBridgeRepairer('model',proposal_format='other')

if __name__=='__main__':unittest.main()
