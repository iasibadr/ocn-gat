import unittest
from ocn_core.change_monitor import ChangeMonitor


class ChangeMonitorTests(unittest.TestCase):
    def test_constant_and_isolated_failure_are_not_change(self):
        monitor=ChangeMonitor()
        for _ in range(100):result=monitor.observe(1.)
        self.assertFalse(result['detected'])
        self.assertFalse(monitor.observe(0.)['detected'])
        self.assertFalse(result['policy_changed'])

    def test_persistent_change_detects_both_directions(self):
        for before,after,direction in ((1.,0.,'degraded'),(0.,1.,'improved')):
            monitor=ChangeMonitor()
            for _ in range(64):monitor.observe(before)
            results=[monitor.observe(after) for _ in range(32)]
            detections=[r for r in results if r['detected']]
            self.assertTrue(detections)
            self.assertEqual(detections[0]['direction'],direction)
            self.assertGreater(abs(detections[0]['mean_shift']),detections[0]['threshold'])

    def test_check_budget_expires_without_silent_reset(self):
        monitor=ChangeMonitor(half_window=2,max_checks=1)
        for _ in range(3):self.assertIsNone(monitor.observe(.5)['detected'])
        self.assertEqual(monitor.observe(.5)['checks'],1)
        old=list(monitor.values)
        result=monitor.observe(1.)
        self.assertEqual(result['status'],'exhausted');self.assertIsNone(result['detected'])
        self.assertEqual(list(monitor.values),old);self.assertEqual(monitor.observations,4)

    def test_invalid_input_does_not_consume_observation(self):
        monitor=ChangeMonitor()
        for value in (True,-1.,1.1,float('nan')):
            with self.assertRaises(ValueError):monitor.observe(value)
        self.assertEqual(monitor.observations,0)
        for args in (dict(half_window=True),dict(max_checks=0),dict(alpha=1.)):
            with self.assertRaises(ValueError):ChangeMonitor(**args)


if __name__=='__main__':unittest.main()
