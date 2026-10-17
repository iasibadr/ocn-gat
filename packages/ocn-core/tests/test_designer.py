from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from ocn_core.designer import design, instantiate
from ocn_core import gat


class DesignerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.habitat=self.root/'docs';self.habitat.mkdir()
        (self.habitat/'a.md').write_text('Delivery Friday.')
        (self.habitat/'b.md').write_text('Weather sunny.')
        self.catalog=[dict(document_id='delivery',path='a.md',description='Delivery schedule'),
                      dict(document_id='weather',path='b.md',description='Weather')]
        self.agent=self.root/'agent'

    def response(self, ids=None, **extra):
        return dict(response=dict(documents=['delivery'] if ids is None else ids,
            rationale='Delivery source supports the mission.',abstain=False,**extra),usage={'model':'designer'})

    def plan(self, answer=None):
        return design(self.habitat,self.catalog,'When is delivery?','executor',
            Mock(return_value=self.response() if answer is None else answer))

    def test_design_preserves_authority_and_runtime(self):
        plan=self.plan()
        self.assertEqual(plan['mission'],'When is delivery?')
        self.assertEqual(plan['runtime_model'],'executor')
        self.assertEqual([d['document_id'] for d in plan['documents']],['delivery'])
        self.assertFalse(self.agent.exists())
        instantiate(self.agent,plan)
        state=gat.status(self.agent)
        self.assertEqual(state['model'],'executor')
        self.assertEqual(state['documents'],['delivery'])

    def test_unknown_duplicate_empty_and_injected_permissions(self):
        for answer in (self.response(['outside']),self.response(['delivery','delivery']),
                       self.response([]),self.response(tools=['shell'])):
            with self.subTest(answer=answer):
                with self.assertRaises(ValueError):self.plan(answer)
        self.assertFalse(self.agent.exists())

    def test_abstention_creates_no_agent(self):
        answer=self.response([]);answer['response']['abstain']=True
        plan=self.plan(answer)
        with self.assertRaises(ValueError):instantiate(self.agent,plan)
        self.assertFalse(self.agent.exists())

    def test_stale_plan_fails_closed(self):
        plan=self.plan();(self.habitat/'a.md').write_text('Delivery Monday.')
        with self.assertRaisesRegex(ValueError,'changed since design'):instantiate(self.agent,plan)
        self.assertFalse((self.agent/'lifecycle.json').exists())
        with self.assertRaises(OSError):gat.run(self.agent,synthesizer=Mock())

    def test_bad_catalog_refused_before_model(self):
        model=Mock(side_effect=AssertionError('No inference'))
        self.catalog[0]['path']='../outside.md'
        with self.assertRaises(ValueError):design(self.habitat,self.catalog,'Read','executor',model)
        model.assert_not_called()

    def test_selection_must_fit_execution_context(self):
        (self.habitat/'a.md').write_text('x'*13000)
        with self.assertRaisesRegex(ValueError,'context budget'):self.plan()
        self.assertFalse(self.agent.exists())

    def test_malformed_and_oversized_plan(self):
        plan=self.plan();plan['documents'][0]['sha256']='invalid'
        with self.assertRaises(ValueError):instantiate(self.agent,plan)
        self.assertFalse(self.agent.exists())
        plan=self.plan();plan['designer_usage']={'unbounded':'x'*70000}
        with self.assertRaises(ValueError):instantiate(self.agent,plan)

if __name__=='__main__':unittest.main()
