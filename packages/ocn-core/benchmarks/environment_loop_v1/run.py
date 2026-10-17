"""Development causal ablation of remembered environmental rejection."""
import hashlib
import json
from pathlib import Path
import random
import tempfile
from ocn_core import CompactAgent,CompactDNA,CompactReservoir,DissipativeHabitat
HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parents[1]

class NoFeedbackMemory(CompactAgent):
    def emit_pending(self,n,tools):
        # Same receipts, compaction and permissions; only retry memory removed.
        self.retirement['retry_after']=n
        self.retirement['backoff']=1
        return super().emit_pending(n,tools)

def episode(seed,policy,feedback,period):
    rng=random.Random(seed);values=[rng.randrange(1000) for _ in range(64)]
    with tempfile.TemporaryDirectory(prefix='ocn-loop-') as root:
        root=Path(root);h=root/'h';h.mkdir()
        dna=CompactDNA(max_calls=4,source_ids=('s',),aggregation='eager',emission_limit=1,
                       learning_scope='source',known_unsupported_reactive=True)
        agent=(CompactAgent if feedback else NoFeedbackMemory)(policy,{'s':'s.json'},dna,seed)
        identity=agent.identity;sink=CompactReservoir(root/'sink',2);trace=[]
        for n,value in enumerate(values):
            if n and n%period==0:sink.drain(1)
            # Structural perturbations create retirement; sink load comes only from emissions.
            nested=(n//2)%2==1
            doc=dict(source='s',step=n)
            if nested:doc['data']=dict(measure=value)
            else:doc['value']=value
            (h/'s.json').write_text(json.dumps(doc))
            (h/'directory.json').write_text(json.dumps({'s':'s.json'}))
            (h/'schemas.json').write_text(json.dumps({'s':dict(codec='integer',value_path=['data','measure'] if nested else ['value'])}))
            before=sink.status()['load'];tools=DissipativeHabitat(h,dna,sink)
            result=agent.step(n,tools);after=sink.status()['load']
            expected=dict(sum=value,records=[dict(source='s',step=n,value=value,path='s.json')])
            state=agent.retirement
            assert agent.identity==identity and result['cost']<=4
            assert state['retired_events']==state['accepted_events']+sum(e['count'] for e in state['pending'])
            assert result['output']==expected
            trace.append(dict(step=n,calls=result['cost'],success=True,load_before=before,load_after=after,
                accepted=state['accepted_events'],retired=state['retired_events'],pending=len(state['pending']),
                refused=sum(r.get('accepted') is False for r in result['dissipation']['receipts']),
                emissions=sum(c['operation']=='dissipate' for c in result['calls']),retry_after=state['retry_after']))
        return dict(seed=seed,policy=policy,feedback=feedback,drain_period=period,
            successes=64,calls=sum(t['calls'] for t in trace),refused=sum(t['refused'] for t in trace),
            emissions=sum(t['emissions'] for t in trace),accepted=state['accepted_events'],retired=state['retired_events'],trace=trace)

def main():
    out=HERE/'results.json'
    if out.exists():raise FileExistsError(out)
    files=[Path(__file__),*sorted((PACKAGE/'src/ocn_core').glob('*.py'))]
    def hashes():return {str(p.relative_to(PACKAGE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    sources=hashes();rows=[]
    for period in (4,16):
        for policy in ('reactive','classical_learner','ocn_hamilton'):
            for feedback in (False,True):
                for seed in range(352000,352004):rows.append(episode(seed,policy,feedback,period))
    assert sources==hashes()
    summary=[]
    for period in (4,16):
        for policy in ('reactive','classical_learner','ocn_hamilton'):
            for feedback in (False,True):
                group=[r for r in rows if (r['drain_period'],r['policy'],r['feedback'])==(period,policy,feedback)]
                summary.append(dict(period=period,policy=policy,feedback=feedback,**{k:sum(r[k] for r in group) for k in ('successes','calls','refused','emissions','accepted','retired')}))
    out.write_text(json.dumps(dict(kind='development_not_reserved',sources=sources,episodes=len(rows),tasks=64*len(rows),summary=summary,rows=rows),indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
