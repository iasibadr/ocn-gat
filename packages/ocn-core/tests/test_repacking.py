import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from ocn_core import RepackingAgent, RepackingDNA, ScheduledAgent
from ocn_core import ScheduledDNA, CompactReservoir, DissipativeHabitat, Fault
from ocn_core.checkpoint import snapshot, restore, save_checkpoint, load_checkpoint

class RepackTests(unittest.TestCase):
    def agent(self):
        return RepackingAgent('reactive', {'s':'old'}, RepackingDNA(source_ids=('s',),scheduler='backoff',aggregation='eager'))

    def test_explicit_rejection_reopens_and_keeps_all_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();a=self.agent()
            sink=CompactReservoir(root/'sink',1)
            # First accepted batch fills the reservoir.
            a.replace_memory('paths','s','first',0)
            a.emit_pending(0,DissipativeHabitat(h,a.dna,sink))
            a.replace_memory('paths','s','second',1)
            a.emit_pending(1,DissipativeHabitat(h,a.dna,sink))
            self.assertFalse(a.retirement['pending'][0]['sealed'])
            a.replace_memory('paths','s','third',2)
            self.assertEqual(a.retirement['pending'][0]['count'],2)
            sink.drain(1)
            a.emit_pending(2,DissipativeHabitat(h,a.dna,sink))
            self.assertEqual(a.retirement['accepted_events'],3)
            self.assertEqual(a.retirement['pending'],[])

    def test_accepted_but_lost_receipt_never_reopens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir();a=self.agent();sink=CompactReservoir(root/'sink',2)
            class Lost(DissipativeHabitat):
                def dissipate(self,stream,event):
                    super().dissipate(stream,event)
                    raise Fault('transport_unknown')
            a.replace_memory('paths','s','first',0)
            a.emit_pending(0,Lost(h,a.dna,sink))
            first=a.retirement['pending'][0].copy()
            a.replace_memory('paths','s','second',1)
            self.assertEqual(a.retirement['pending'][0],first)
            self.assertEqual(len(a.retirement['pending']),2)
            a.emit_pending(1,DissipativeHabitat(h,a.dna,sink))
            self.assertEqual(a.retirement['accepted_events'],1)
            self.assertEqual(sink.status()['load'],1)
            a.emit_pending(2,DissipativeHabitat(h,a.dna,sink))
            self.assertEqual(a.retirement['accepted_events'],2)
            self.assertEqual(sink.status()['load'],2)

    def test_two_lots_merge_only_after_definite_refusal(self):
        a=self.agent();a.last_step=2
        a.replace_memory('paths','s','one',0);a.prepare_emission(a.retirement['pending'][0])
        a.replace_memory('paths','s','two',1)
        class Refuse:
            supports_atomic_refusal=True
            calls=[]
            def dissipate(self,stream,event):
                self.calls.append({'operation':'dissipate'})
                return dict(accepted=False,pressure=1.)
        a.emit_pending(2,Refuse())
        self.assertEqual(len(a.retirement['pending']),1)
        self.assertEqual(a.retirement['sequence'],1)
        self.assertEqual(a.retirement['pending'][0]['count'],2)
        self.assertEqual(a.emission_state['born'],{'1':0})
        self.assertEqual(snapshot(a),snapshot(restore(json.loads(json.dumps(snapshot(a))),a.dna,'reactive')))

    def test_crash_after_refusal_then_new_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'h';h.mkdir()
            dna=RepackingDNA(source_ids=('s',),max_calls=4,scheduler='backoff',aggregation='eager',emission_phase='after')
            a=RepackingAgent('reactive',{'s':'old'},dna)
            sink=CompactReservoir(root/'sink',1)
            a.replace_memory('paths','s','s0',0)
            a.emit_pending(0,DissipativeHabitat(h,dna,sink))
            a.replace_memory('paths','s','s1',1)
            (h/'s1').write_text(json.dumps(dict(source='s',step=1,value=7)))
            tools=DissipativeHabitat(h,dna,sink);a.step(1,tools)
            saves=0
            def interrupted(agent,path):
                nonlocal saves
                saves+=1
                if saves==2:raise OSError('lost final checkpoint after refusal')
                save_checkpoint(agent,path)
            with patch('ocn_core.checkpoint.save_checkpoint',side_effect=interrupted):
                with self.assertRaises(OSError):a.finish_request(1,tools,root/'state')
            a=load_checkpoint(root/'state',dna,'reactive');assert isinstance(a,RepackingAgent)
            self.assertTrue(a.retirement['pending'][0]['sealed'])
            (h/'s1').unlink()
            (h/'s2').write_text(json.dumps(dict(source='s',step=2,value=9)))
            (h/'directory.json').write_text(json.dumps({'s':'s2'}))
            tools=DissipativeHabitat(h,dna,sink);a.step(2,tools)
            self.assertEqual(len(a.retirement['pending']),2)
            a.finish_request(2,tools,root/'state')
            a=load_checkpoint(root/'state',dna,'reactive');assert isinstance(a,RepackingAgent)
            self.assertEqual(a.retirement['retired_events'],3)
            self.assertEqual(a.retirement['accepted_events'],1)
            self.assertEqual(len(a.retirement['pending']),1)
            self.assertEqual(a.retirement['pending'][0]['count'],2)
            self.assertFalse(a.retirement['pending'][0]['sealed'])
            self.assertEqual(a.retirement['merges'],1)
            self.assertEqual(sink.status()['load'],1)

    def test_opt_in_contract_and_checkpoint_identity(self):
        a=self.agent()
        class Unspecified:
            calls=[]
        with self.assertRaisesRegex(ValueError,'atomic nonacceptance'):
            a.emit_pending(0,Unspecified())
        self.assertEqual(Unspecified.calls,[])
        payload=json.loads(json.dumps(snapshot(a)))
        self.assertEqual(payload['version'],6)
        ordinary=ScheduledDNA(source_ids=('s',),scheduler='backoff',aggregation='eager')
        with self.assertRaises(ValueError):restore(payload,ordinary,'reactive')
        with self.assertRaises(ValueError):RepackingAgent('reactive',{'s':'old'},ordinary)
        with self.assertRaises(ValueError):RepackingDNA(refusal_contract='unknown')
        with self.assertRaises(ValueError):ScheduledAgent('reactive',{'s':'old'},a.dna)

if __name__=='__main__':unittest.main()
