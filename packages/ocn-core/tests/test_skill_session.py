import unittest
from ocn_core.skill_session import SkillSession


def examples(field='mass'):
    return [dict(record={'id': i, field: f'{n} kg'}, identity=i, expected=f'{n*1000} g')
            for i, n in [('a', 2), ('b', 3)]]


class SessionTests(unittest.TestCase):
    def test_repeated_negative_lookup_does_not_displace_useful_method(self):
        from ocn_core.skill_bank import SkillBank
        bank=SkillBank(capacity=2); ambiguous=examples()
        for row in ambiguous: row['record']['duplicate']=row['record']['mass']
        bank.authorize('A','1',ambiguous)
        bank.authorize('B','1',examples()); bank.authorize('C','1',examples())
        record={'id':'new','mass':'4 kg'}
        bank.read('A','1',record,'new'); bank.read('B','1',record,'new')
        bank.read('A','1',record,'new'); bank.read('C','1',record,'new')
        self.assertEqual(list(bank.entries), ['B','C'])

    def session(self, **kwargs):
        self.calls = []
        def worker(c, r, record, identity, calibration):
            self.calls.append(identity)
            return {'value': '4000 g'}
        return SkillSession(worker, lambda c,r,s,i,o: o['value'] == '4000 g', **kwargs)

    def run_task(self, s, **kwargs):
        costs = dict(allowance=12, acquisition_cost=3, application_cost=1, delegation_cost=8)
        costs.update(kwargs)
        return s.run('A', '1', {'id':'new', 'mass':'4 kg'}, 'new', **costs)

    def test_transfer_and_budget_admission(self):
        s = self.session(); s.authorize('A','1', examples())
        self.assertEqual(self.run_task(s, allowance=8)['action'], 'delegate')
        self.assertEqual(s.bank.attempts, 0)
        self.assertEqual(self.run_task(s)['action'], 'acquire_apply')
        result = s.run('A','1',{'id':'other','mass':'4 kg'},'other',
                       allowance=1,acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(result['action'], 'apply')
        self.assertEqual(self.calls, ['new'])

    def test_negative_memory_and_revision_recovery(self):
        s=self.session(); e=examples()
        for row in e: row['record']['duplicate']=row['record']['mass']
        s.authorize('A','1',e)
        self.assertEqual(self.run_task(s)['action'], 'acquire_delegate')
        self.assertEqual(self.run_task(s)['action'], 'delegate')
        self.assertEqual(s.bank.attempts, 1)
        s.authorize('A','1',examples())
        self.assertEqual(self.run_task(s)['action'], 'acquire_apply')

    def test_semantic_rejection_disables_method(self):
        s=self.session(); s.authorize('A','1',examples())
        s.evaluate=lambda *args: False
        with self.assertRaisesRegex(ValueError,'semantic'): self.run_task(s)
        self.assertEqual(self.calls, [])
        s.evaluate=lambda *args: True
        self.assertEqual(self.run_task(s)['action'], 'delegate')
        self.assertEqual(s.bank.attempts, 1)

    def test_wrong_entity_does_not_trigger_weaker_fallback(self):
        s=self.session(); s.authorize('A','1',examples())
        self.run_task(s)
        with self.assertRaisesRegex(ValueError,'entity'):
            s.run('A','1',{'id':'wrong','mass':'4 kg'},'new',allowance=12,
                  acquisition_cost=3,application_cost=1,delegation_cost=8)
        self.assertEqual(self.calls, [])

    def test_failed_worker_charged_and_revision_refused(self):
        s=self.session(max_worker_calls=1); s.authorize('A','1',examples())
        def fail(*args): raise OSError('worker down')
        s.worker=fail
        with self.assertRaises(OSError): self.run_task(s,allowance=8)
        self.assertEqual(s.worker_calls,1)
        with self.assertRaises(RuntimeError): self.run_task(s,allowance=8)
        with self.assertRaisesRegex(ValueError,'authority'):
            s.run('A','2',{},'x',allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8)


if __name__ == '__main__': unittest.main()
