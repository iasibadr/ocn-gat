"""Optional bounded wait/emit selector; not a claim of quaternion superiority."""
from dataclasses import dataclass
import numpy as np
from .compact import CompactAgent,CompactDNA
from .controller import Predictor

@dataclass(frozen=True)
class ScheduledDNA(CompactDNA):
    emission_limit: int = 1
    scheduler: str = 'ocn_hamilton'
    reaction_horizon: int = 8
    def __post_init__(self):
        super().__post_init__()
        if self.scheduler not in ('backoff','periodic4','paced16','paced32','classical_learner','ocn_hamilton','ocn_real'):
            raise ValueError('Invalid emission scheduler')
        if type(self.reaction_horizon) is not int or not 1<=self.reaction_horizon<=32:
            raise ValueError('Invalid reaction horizon')
        if self.emission_limit!=1:raise ValueError('Scheduled emission requires one attempt per request')

class ScheduledAgent(CompactAgent):
    def __init__(self,policy,initial_paths,dna,seed=0):
        if not isinstance(dna,ScheduledDNA):raise ValueError('Scheduled DNA required')
        from .repacking import RepackingDNA, RepackingAgent
        if isinstance(dna,RepackingDNA) and not isinstance(self,RepackingAgent):
            raise ValueError('Repacking DNA requires RepackingAgent')
        super().__init__(policy,initial_paths,dna,seed)
        self.emission_state=dict(last_attempt=0,refusal_ema=0.,born={})
        self.emission_model=Predictor(dna.scheduler)

    def replace_memory(self,field,source,value,n):
        super().replace_memory(field,source,value,n)
        # One timestamp per pending batch, including merges: no per-transition log.
        for event in self.retirement['pending']:
            self.emission_state['born'].setdefault(str(event['sequence']),n)

    def emission_decision(self,n,tools):
        state=self.retirement;memory=self.emission_state
        if not state['pending'] or self.emission_room(tools)<1:return False,None,None
        elapsed=n-memory['last_attempt'];head=state['pending'][0]
        oldest=n-memory['born'][str(head['sequence'])]
        z=np.array([min(1.,sum(e['count'] for e in state['pending'])/8),
                    min(1.,elapsed/16),state['pressure'],memory['refusal_ema']])
        prediction=None
        if self.dna.scheduler=='backoff':emit=n>=state['retry_after']
        elif self.dna.scheduler=='periodic4':emit=elapsed>=4
        elif self.dna.scheduler in ('paced16','paced32'):
            emit=elapsed>=int(self.dna.scheduler[5:]) and n>=state['retry_after']
        else:
            prediction=self.emission_model.predict(z)[0]+np.array([.5,0.,0.,0.])
            probability=float(np.clip(prediction[0],0,1))
            gain=probability*min(1.,head['count']/8)*(1+min(oldest,32)/16)
            emit=gain>=.10+.15*(1-probability) or elapsed>=self.dna.reaction_horizon
            emit=emit and n>=state['retry_after']
        return bool(emit),z,prediction

    def will_emit(self,n,tools):
        return self.emission_decision(n,tools)[0]

    def emit_pending(self,n,tools):
        emit,z,prediction=self.emission_decision(n,tools)
        self.last_emissions=[]
        if not emit:return
        state=self.retirement;memory=self.emission_state
        if self.dna.scheduler=='periodic4':state['retry_after']=n;state['backoff']=1
        before=state['accepted_events'];calls=len(tools.calls)
        super().emit_pending(n,tools)
        if len(tools.calls)==calls:return
        state['retry_after']=min(state['retry_after'],n+self.dna.reaction_horizon)
        state['backoff']=min(state['backoff'],self.dna.reaction_horizon)
        memory['last_attempt']=n
        accepted=state['accepted_events']-before
        live={str(e['sequence']) for e in state['pending']}
        memory['born']={k:v for k,v in memory['born'].items() if k in live}
        refused=any(r.get('accepted') is False for r in self.last_emissions)
        memory['refusal_ema']=.8*memory['refusal_ema']+.2*float(refused)
        if prediction is not None:
            debt=sum(e['count'] for e in state['pending'])
            target=np.array([float(accepted>0),state['pressure'],float(refused),min(1.,debt/8)])
            self.emission_model.update(z,0,target,prediction)
