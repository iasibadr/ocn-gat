"""Do not require a repair search budget when current behavior already passes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.hybrid_repair import hybrid_repair
from ocn_core.local_repair import local_repair,variations

PACKAGE=Path(__file__).resolve().parents[1]

class AcceptanceFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);docs=self.root/'docs';docs.mkdir();(docs/'a.md').write_text('Friday')
        self.instance=self.root/'instance';self.audit=self.root/'audit'
        code=(PACKAGE/'benchmarks/bridge_repair_v7/trim.py').read_bytes()
        self.integration=Integration(code,'build_synthesizer')
        gat.create(self.instance,docs,{'a':'a.md'},'a',integration=self.integration,isolated=True)
        self.suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='plain',question='a',documents=[dict(document_id='a',text='Friday')],
            expected=dict(response=dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')])) )])
    def test_accepted_agent_never_enumerates_repairs_or_calls_designer(self):
        self.assertEqual(len(variations(self.integration)),2)
        proposer=Mock()
        with patch('ocn_core.local_repair.variations',wraps=variations) as search:
            result=hybrid_repair(self.instance,'Return the supplied text.',self.suite,proposer,self.audit,limit=1)
            self.assertEqual(result['status'],'already_accepted')
            self.assertEqual(result['local']['tested_candidates'],0)
            search.assert_not_called();proposer.assert_not_called()
        self.assertEqual(gat.run(self.instance)['answer'],'Friday')
    def test_failed_acceptance_preserves_search_limit_and_no_fallback(self):
        case=self.suite['cases'][0];case['documents'][0]['text']=' Friday '
        case['expected']['response'].update(answer=' Friday ',citations=[dict(document_id='a',quote=' Friday ')])
        proposer=Mock()
        with self.assertRaisesRegex(ValueError,'exceeds explicit limit'):
            hybrid_repair(self.instance,'Return exact spaces.',self.suite,proposer,self.audit,limit=1)
        proposer.assert_not_called()
        baseline=json.loads((self.audit/'local/baseline.json').read_text())
        self.assertFalse(baseline['accepted'])
        self.assertEqual(gat.run(self.instance)['answer'],'Friday')
    def test_invalid_limit_rejected_before_any_evaluation(self):
        with patch('ocn_core.local_repair.evaluate') as evaluate:
            for limit in (True,0,9):
                with self.assertRaises(ValueError):local_repair(self.instance,self.suite,self.audit,limit=limit)
            evaluate.assert_not_called()
        self.assertFalse(self.audit.exists())

if __name__=='__main__':unittest.main()
