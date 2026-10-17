import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import (RepackingAgent,RepackingDNA,CompactAgent,CompactDNA,
                      CompactReservoir,DissipativeHabitat,load_checkpoint,save_checkpoint)
from ocn_core.checkpoint import canonical,snapshot

class CheckpointWriteTests(unittest.TestCase):
    def habitat(self,p,dna):
        h=p/'h';h.mkdir();(h/'s').write_text(json.dumps(dict(source='s',step=0,value=7)))
        return DissipativeHabitat(h,dna,CompactReservoir(p/'sink',2))

    def test_wait_writes_once_and_restores_complete_current_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);dna=RepackingDNA(source_ids=('s',),scheduler='paced32',emission_phase='after',aggregation='eager')
            a=RepackingAgent('reactive',{'s':'old'},dna)
            a.replace_memory('paths','s','s',0)
            tools=self.habitat(p,dna);a.step(0,tools)
            with patch('ocn_core.checkpoint.save_checkpoint',wraps=save_checkpoint) as save:
                result=a.finish_request(0,tools,p/'state')
            self.assertEqual(save.call_count,1)
            self.assertEqual(result['output']['sum'],7)
            self.assertEqual(result['dissipation']['accepted_events'],0)
            self.assertEqual(canonical(snapshot(a)),canonical(snapshot(load_checkpoint(p/'state',dna,'reactive'))))

    def test_memory_change_without_tool_call_is_still_saved(self):
        class MemoryOnly(CompactAgent):
            def emit_pending(self,n,tools):self.temperature=.2
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);dna=CompactDNA(source_ids=('s',),emission_phase='after')
            a=MemoryOnly('reactive',{'s':'s'},dna);tools=self.habitat(p,dna)
            a.step(0,tools);before=len(tools.calls)
            with patch('ocn_core.checkpoint.save_checkpoint',wraps=save_checkpoint) as save:
                a.finish_request(0,tools,p/'state')
            self.assertEqual(len(tools.calls),before)
            self.assertEqual(save.call_count,2)
            self.assertEqual(load_checkpoint(p/'state',dna,'reactive').temperature,.2)

if __name__=='__main__':unittest.main()
