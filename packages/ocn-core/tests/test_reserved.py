from pathlib import Path
import sqlite3
import tempfile
import unittest
from ocn_core import CompactReservoir,Fault
from ocn_core.reserved import ReservedCompactReservoir
from ocn_core import (RepackingAgent,ReservedRepackingDNA,RepackingDNA,DissipativeHabitat,
    ToolSession,save_checkpoint,load_checkpoint)


def event(sequence,digest='b'*64):return dict(sequence=sequence,digest=digest,count=3,sealed=True)

class ReservedTests(unittest.TestCase):
    def test_dna_binding_persists_and_wrong_destination_rejects_before_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            options=dict(source_ids=('s',),max_cache=1,max_calls=4,scheduler='paced32',emission_phase='after')
            dna=ReservedRepackingDNA(**options,destination_capacity=2,destination_reserve=1)
            agent=RepackingAgent('reactive',{'s':'data'},dna)
            save_checkpoint(agent,root/'state');original=(root/'state').read_bytes()
            for sink in (CompactReservoir(root/'legacy',2),ReservedCompactReservoir(root/'wrong',2,0)):
                tools=DissipativeHabitat(h,dna,sink)
                with self.assertRaisesRegex(ValueError,'contract mismatch'):ToolSession(agent,tools,0)
                self.assertEqual(tools.calls,[]);self.assertEqual(agent.last_step,-1)
            agent=load_checkpoint(root/'state',dna,'reactive')
            self.assertIsInstance(agent.dna,ReservedRepackingDNA)
            with self.assertRaises(ValueError):load_checkpoint(root/'state',RepackingDNA(**options),'reactive')
            self.assertEqual((root/'state').read_bytes(),original)
            sink=ReservedCompactReservoir(root/'correct',2,1)
            session=ToolSession(agent,DissipativeHabitat(h,dna,sink),0)
            session.persist(root/'state')
            agent=load_checkpoint(root/'state',dna,'reactive')
            self.assertTrue(agent.maintain(32,DissipativeHabitat(h,dna,sink),root/'state')['maintenance_complete'])

    def test_refusal_dedup_and_reopen_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sink';r=ReservedCompactReservoir(path,2,1)
            self.assertEqual(r.accept('a'*32,event(1)),dict(accepted=True,pressure=.5))
            before=r.status()
            self.assertEqual(r.accept('a'*32,event(2)),dict(accepted=False,pressure=.5))
            self.assertEqual(r.status(),before)
            r=ReservedCompactReservoir(path,2,1)
            self.assertEqual(r.accept('a'*32,event(1)),dict(accepted=True,pressure=.5))
            with self.assertRaises(Fault):r.accept('a'*32,event(1,'c'*64))
            with self.assertRaises(ValueError):ReservedCompactReservoir(path,2,0)
            self.assertEqual(r.status(),before)
            self.assertEqual(r.descriptor()['reserve'],1)
            r.drain(1);self.assertTrue(r.accept('a'*32,event(2))['accepted'])
            self.assertEqual(r.status()['load'],1)

    def test_legacy_client_cannot_open_and_reserved_client_refuses_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r=ReservedCompactReservoir(root/'new',2,1)
            before=r.status()
            with self.assertRaises(sqlite3.Error):CompactReservoir(root/'new',2)
            self.assertEqual(r.status(),before)
            ReservedCompactReservoir(root/'new',2,1)
            legacy=CompactReservoir(root/'old',2);legacy.accept('a'*32,event(1));old=legacy.status()
            with self.assertRaises(ValueError):ReservedCompactReservoir(root/'old',2,1)
            self.assertEqual(legacy.status(),old)

    def test_sql_invariant_and_immutable_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ReservedCompactReservoir(Path(tmp)/'sink',2,1)
            for sql in ('UPDATE ocn_reserved SET load=2','UPDATE ocn_reserved SET reserve=0',
                        'INSERT INTO state VALUES (2,2,0,NULL,0,NULL)'):
                with self.assertRaises(sqlite3.Error):
                    with r.connect() as db:db.execute(sql)
            self.assertEqual(r.status(),dict(capacity=2,reserve=1,load=0,sequence=0))

    def test_zero_reserve_matches_legacy_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=CompactReservoir(root/'a',2);b=ReservedCompactReservoir(root/'b',2,0)
            sequence=1
            for tick in range(50):
                if tick%3==0:a.drain(1);b.drain(1)
                expected=a.accept('a'*32,event(sequence))
                self.assertEqual(b.accept('a'*32,event(sequence)),expected)
                self.assertEqual({k:b.status()[k] for k in a.status()},a.status())
                if expected['accepted']:
                    self.assertEqual(b.accept('a'*32,event(sequence)),a.accept('a'*32,event(sequence)))
                    sequence+=1

if __name__=='__main__':unittest.main()
