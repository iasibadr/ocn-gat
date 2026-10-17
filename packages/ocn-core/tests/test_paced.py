from dataclasses import asdict
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from ocn_core import RepackingAgent, RepackingDNA, CompactReservoir, DissipativeHabitat, save_checkpoint, load_checkpoint

class PacedTests(unittest.TestCase):
    def test_protected_periods(self):
        class Tools:calls=[]
        for period in (16,32):
            a=RepackingAgent('reactive',{'s':'old'},RepackingDNA(source_ids=('s',),scheduler=f'paced{period}'))
            a.replace_memory('paths','s','new',0)
            self.assertFalse(a.emission_decision(period-1,Tools())[0])
            self.assertTrue(a.emission_decision(period,Tools())[0])
            a.retirement['retry_after']=period+2
            self.assertFalse(a.emission_decision(period+1,Tools())[0])
            self.assertTrue(a.emission_decision(period+2,Tools())[0])

    def test_extraction_parity_and_restoration_both_phases(self):
        package=Path(__file__).resolve().parents[1]
        prototype=runpy.run_path(str(package/'benchmarks/service_cadence_v1/policy.py'))['CadenceAgent']
        for period in (16,32):
            for phase in ('before','after'):
                with self.subTest(period=period,phase=phase),tempfile.TemporaryDirectory() as tmp:
                    p=Path(tmp);h=p/'h';h.mkdir()
                    dna=RepackingDNA(source_ids=('s',),max_calls=4,scheduler=f'paced{period}',aggregation='eager',emission_phase=phase)
                    old_dna=RepackingDNA(**{**asdict(dna),'scheduler':'backoff'})
                    a=prototype('reactive',{'s':'s'},old_dna);a.cadence_mode=f'fixed{period}'
                    b=RepackingAgent('reactive',{'s':'s'},dna);b.retirement['stream']=a.retirement['stream']
                    sinks=[CompactReservoir(p/f'sink{i}',2) for i in range(2)]
                    for n in range(96):
                        nested=(n//2)%2==1
                        doc=dict(source='s',step=n)
                        if nested:doc['data']={'value':n}
                        else:doc['value']=n
                        (h/'s').write_text(json.dumps(doc))
                        (h/'schemas.json').write_text(json.dumps({'s':dict(codec='integer',value_path=['data','value'] if nested else ['value'])}))
                        if n%16==0:
                            for sink in sinks:sink.drain(1)
                        results=[]
                        for i,agent in enumerate((a,b)):
                            tools=DissipativeHabitat(h,agent.dna,sinks[i]);r=agent.step(n,tools)
                            if phase=='after':r=agent.finish_request(n,tools,p/f'state{i}')
                            results.append(r)
                        for key in ('output','cost','calls','decisions','dissipation'):
                            self.assertEqual(results[0][key],results[1][key])
                        self.assertEqual(a.retirement,b.retirement)
                        if n==47:
                            save_checkpoint(b,p/'restart');b=load_checkpoint(p/'restart',dna,'reactive')
                            self.assertEqual(b.dna.scheduler,f'paced{period}')

if __name__=='__main__':unittest.main()
