import unittest
from ocn_core.mass_read_skill import accept,discover

class MassReadSkillTests(unittest.TestCase):
    def examples(self):
        return [dict(record=dict(id='A',mass='2 kg'),identity='A',expected='2000 g'),
                dict(record=dict(id='B',mass='300 g'),identity='B',expected='300 g')]

    def test_reuse_and_entity_revision_boundaries(self):
        c,r=discover(self.examples(),connector='inventory',revision='1')
        self.assertEqual(r['model_calls'],0)
        self.assertEqual(c.apply(dict(id='C',mass='9 kg'),connector='inventory',revision='1',expected_identity='C')['value'],'9000 g')
        for connector,revision,entity in [('other','1','C'),('inventory','2','C'),('inventory','1','D')]:
            with self.assertRaises(ValueError):c.apply(dict(id='C',mass='9 kg'),connector=connector,revision=revision,expected_identity=entity)

    def test_ambiguity_never_selects_first_match(self):
        e=self.examples()
        for x in e:x['record']['duplicate']=x['record']['mass']
        with self.assertRaisesRegex(ValueError,'found 2'):discover(e,connector='inventory',revision='1')

    def test_malformed_host_examples(self):
        for bad in (None,{},[{}]*2,[dict(record={},identity=[],expected='1 g')]*2):
            with self.assertRaises(ValueError):discover(bad,connector='inventory',revision='1')

    def test_cycles_and_depth_rejected(self):
        e=self.examples();e[0]['record']['cycle']=e[0]['record']
        with self.assertRaises(ValueError):discover(e,connector='inventory',revision='1')

    def test_changed_shape_and_unapproved_units(self):
        c,_=discover(self.examples(),connector='inventory',revision='1')
        for record in (dict(id='C',mass='4 USD'),dict(id='C',mass='4 kg',extra='x')):
            with self.assertRaises(ValueError):c.apply(record,connector='inventory',revision='1',expected_identity='C')

    def test_nested_quantity_and_budget(self):
        e=[dict(record=dict(entity=dict(id=i),mass=dict(amount=a,unit='kg')),identity=i,expected=v)
           for i,a,v in [('A',2,'2000 g'),('B',3,'3000 g')]]
        c,_=discover(e,connector='inventory',revision='1')
        self.assertEqual(c.quantity,('mass','amount'))
        with self.assertRaisesRegex(ValueError,'budget'):discover(e,connector='inventory',revision='1',max_candidates=1)

    def test_executable_extension_refused(self):
        with self.assertRaises(ValueError):accept(dict(identity=['id'],quantity=['mass'],unit=None,code='exec'),self.examples(),connector='inventory',revision='1')

class SessionTests(unittest.TestCase):
    def test_reuse_revision_reacquisition_and_close(self):
        from ocn_core.mass_read_skill import MassSkillSession
        examples=MassReadSkillTests().examples()
        changed=[dict(record=dict(id=e['identity'],amount=e['record']['mass']),identity=e['identity'],expected=e['expected']) for e in examples]
        config={'v1':examples,'v2':changed}
        session=MassSkillSession(connector='inventory',calibration=config)
        config.clear()
        for _ in range(2):self.assertEqual(session.read(dict(id='C',mass='8 kg'),revision='v1',expected_identity='C')['value'],'8000 g')
        self.assertEqual(session.acquisitions,1)
        self.assertEqual(session.read(dict(id='C',amount='9 kg'),revision='v2',expected_identity='C')['value'],'9000 g')
        self.assertEqual(session.acquisitions,2)
        with self.assertRaises(ValueError):session.read(dict(id='C',amount='9 kg'),revision='untrusted',expected_identity='C')
        session.close()
        with self.assertRaisesRegex(ValueError,'closed'):session.read(dict(id='C',amount='9 kg'),revision='v2',expected_identity='C')

    def test_broad_records_are_bounded(self):
        from ocn_core.mass_read_skill import shape
        record={str(i):{str(j):'x' for j in range(32)} for i in range(32)}
        with self.assertRaisesRegex(ValueError,'node budget'):shape(record)
