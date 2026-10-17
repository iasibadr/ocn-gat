import tempfile
import unittest
import sys
from pathlib import Path

from ocn_core.document_adapter import DocumentAdapter
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.ocn_probe_lease_v2.run import LeasedRiskClassic, TEXTS


class LeaseTests(unittest.TestCase):
    def test_receipt_is_consumed_and_classical_preference_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            routes = {}
            for name in ('primary','mirror'):
                root = base/name
                root.mkdir()
                adapter = DocumentAdapter(root,base/(name+'.json'))
                (root/'A.txt').write_text(TEXTS['A'])
                adapter.bind('A','A.txt')
                routes[name] = adapter
            controller = LeasedRiskClassic(routes)
            (base/'primary/A.txt').unlink()
            controller.begin_request(1)
            observed = controller.observe('A')
            self.assertEqual(observed['action'],'probe')
            self.assertEqual(controller.lease['A']['route'],'mirror')
            self.assertEqual(controller.read('A').path,'mirror/A.txt')
            controller.end_request()
            self.assertEqual(controller.lease,{})
            self.assertEqual(controller.preferred['A'],'mirror')
            controller.begin_request(2)
            controller.observe(None)
            before = controller.failures
            self.assertEqual(controller.read('A').path,'mirror/A.txt')
            self.assertEqual(controller.failures,before)
            controller.end_request()


if __name__ == '__main__':
    unittest.main()
