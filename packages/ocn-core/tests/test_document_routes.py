import tempfile,unittest
from pathlib import Path
from ocn_core.document_routes import RouteAdapter,DocumentAdapter
class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.routes={}
        for name in ('primary','mirror'):
            root=self.base/name;root.mkdir();(root/'a.txt').write_text('origin Taza')
            a=DocumentAdapter(root,self.base/(name+'.json'));a.bind('A','a.txt');self.routes[name]=a
    def tearDown(self):self.temp.cleanup()
    def test_recovery_preference_and_pinned_version(self):
        a=RouteAdapter(self.routes);(self.base/'primary/a.txt').unlink()
        self.assertEqual(a.read('A').path,'mirror/a.txt');self.assertEqual(a.attempts,2)
        a.read('A');self.assertEqual(a.attempts,3)
        (self.base/'mirror/a.txt').write_text('origin Rabat')
        with self.assertRaisesRegex(ValueError,'all authorized'):a.read('A')
    def test_reject_different_versions_at_enrollment(self):
        b=self.routes['mirror'];(self.base/'mirror/b.txt').write_text('different');b.bind('B','b.txt')
        with self.assertRaisesRegex(ValueError,'identical'):RouteAdapter(self.routes)
    def test_unknown_identity_spends_no_attempt(self):
        a=RouteAdapter(self.routes)
        with self.assertRaises(ValueError):a.read('unknown')
        self.assertEqual(a.attempts,0)
    def test_hysteresis_ignores_transient_failure_then_switches_on_repeated_verified_reads(self):
        a=RouteAdapter(self.routes,policy='hysteretic')
        primary=self.base/'primary/a.txt';primary.unlink()
        self.assertEqual(a.read('A').path,'mirror/a.txt')
        self.assertEqual(a.snapshot()['preferred'],{'A':'primary'})
        primary.write_text('origin Taza')
        self.assertEqual(a.read('A').path,'primary/a.txt')
        primary.unlink()
        self.assertEqual(a.read('A').path,'mirror/a.txt')
        self.assertEqual(a.snapshot()['switches'],0)
        self.assertEqual(a.read('A').path,'mirror/a.txt')
        self.assertEqual(a.snapshot()['preferred'],{'A':'mirror'})
        self.assertEqual(a.snapshot()['switches'],1)
        attempts=a.attempts
        self.assertEqual(a.read('A').path,'mirror/a.txt')
        self.assertEqual(a.attempts,attempts+1)
        (self.base/'mirror/a.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'all authorized'):a.read('A')
        self.assertEqual(a.snapshot()['switches'],1)
if __name__=='__main__':unittest.main()
