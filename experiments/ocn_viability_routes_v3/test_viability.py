import sys
import tempfile
import unittest
from pathlib import Path

from ocn_core.document_adapter import DocumentAdapter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.ocn_viability_routes_v3.run import ViabilityRoutes, TEXTS


class ViabilityTests(unittest.TestCase):
    def test_failed_route_is_avoided_but_fallback_can_restore_it(self):
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
            agent = ViabilityRoutes(routes)
            (base/'primary/A.txt').unlink()
            agent.begin_request(0)
            agent.observe(None)
            self.assertEqual(agent.read('A').path,'mirror/A.txt')
            self.assertGreaterEqual(agent.bad_until['A']['primary'],2)
            agent.end_request()
            agent.begin_request(1)
            agent.observe(None)
            failures = agent.failures
            self.assertEqual(agent.read('A').path,'mirror/A.txt')
            self.assertEqual(agent.failures,failures)
            self.assertEqual(agent.route_choices[-1]['mode'],'one_viable')
            agent.end_request()
            (base/'primary/A.txt').write_text(TEXTS['A'])
            (base/'mirror/A.txt').unlink()
            agent.begin_request(2)
            agent.observe(None)
            self.assertEqual(agent.read('A').path,'primary/A.txt')
            self.assertEqual(agent.bad_until['A']['primary'],-1)
            agent.end_request()


if __name__=='__main__':
    unittest.main()
