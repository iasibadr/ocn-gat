import hashlib
from pathlib import Path
import tempfile
from threading import Barrier
import unittest

from ocn_core.document_adapter import DocumentAdapter
from ocn_core.evidence_agent import EvidenceAgent
from ocn_core.extraction_organ import ExtractionOrgan


def worker(q, fields, ident, text):
    return dict(observations=[dict(source_id=ident, field=f,
        sha256=hashlib.sha256(text.encode()).hexdigest(), status='value', value=text, quote=text)
        for f in fields], usage=dict(model_calls=1))


class OrganTests(unittest.TestCase):
    def test_parallel_distinct_cells_and_reuse(self):
        barrier = Barrier(2, timeout=3)
        calls = []
        def extract(*args):
            calls.append(args[2]); barrier.wait(); return worker(*args)
        organ = ExtractionOrgan(extract, lambda: 'v1', max_cells=2)
        ids = {}
        for n in range(30):
            ids.setdefault(organ.cell_for(str(n)), str(n))
        sources = {i: '2 kg' for i in ids.values()}
        first = organ.extract_many('Mass?', {'mass': 'Raw'}, sources)
        again = organ.extract_many('Mass?', {'mass': 'Raw'}, sources)
        self.assertEqual(len(calls), 2)
        self.assertEqual(set(first), set(sources))
        self.assertTrue(all(r['usage']['cache_hit'] for r in again.values()))

    def test_version_and_policy_invalidate(self):
        revision = ['1']; calls = []
        def extract(*args): calls.append(1); return worker(*args)
        organ = ExtractionOrgan(extract, lambda: revision[0])
        for text in ('2 kg', '2 kg', '3 kg'):
            organ.extract_many('Mass?', {'mass':'Raw'}, {'a':text})
        revision[0] = '2'
        organ.extract_many('Mass?', {'mass':'Raw'}, {'a':'3 kg'})
        self.assertEqual(len(calls), 3)

    def test_invalid_batch_never_calls_worker(self):
        def fail(*args): self.fail('worker invoked')
        organ = ExtractionOrgan(fail, lambda:'1')
        for sources in ({}, {'a':'x'*262145}):
            with self.assertRaises(ValueError): organ.extract_many('Q?', {'x':'Raw'}, sources)

    def test_worker_failure_does_not_poison_next_batch(self):
        calls = []
        def extract(*args):
            calls.append(1)
            if len(calls) == 1: raise RuntimeError('worker failed')
            return worker(*args)
        organ = ExtractionOrgan(extract, lambda:'1')
        with self.assertRaises(RuntimeError): organ.extract_many('Q?', {'x':'Raw'}, {'a':'x'})
        self.assertEqual(organ.extract_many('Q?', {'x':'Raw'}, {'a':'x'})['a']['observations'][0]['value'], 'x')

    def test_batch_keeps_final_source_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); docs = root/'docs'; docs.mkdir(); (docs/'a.txt').write_text('2 kg')
            adapter = DocumentAdapter(docs, root/'bindings.json'); adapter.bind('a', 'a.txt')
            def extract(*args):
                (docs/'a.txt').write_text('9 kg'); return worker(*args)
            organ = ExtractionOrgan(extract, lambda:'1')
            agent = EvidenceAgent(adapter, organ, extract_many=organ.extract_many)
            with self.assertRaises(ValueError): agent.answer('Mass?', {'mass':'Raw'}, ('a',))

    def test_batch_cannot_omit_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); docs=root/'docs'; docs.mkdir(); (docs/'a.txt').write_text('2 kg')
            adapter=DocumentAdapter(docs, root/'bindings.json'); adapter.bind('a','a.txt')
            agent=EvidenceAgent(adapter,worker,extract_many=lambda *args:{})
            with self.assertRaisesRegex(ValueError,'coverage'):
                agent.answer('Mass?', {'mass':'Raw'}, ('a',))


if __name__ == '__main__': unittest.main()
