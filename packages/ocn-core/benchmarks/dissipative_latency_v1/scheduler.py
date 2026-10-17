"""Protected wait/emit selection; fixed v1 score, no retuning."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import runpy
import numpy as np
from ocn_core import CompactAgent
from ocn_core.controller import Predictor
HERE=Path(__file__).resolve().parent;PACKAGE=HERE.parents[1]
base=runpy.run_path(str(HERE.parent/'environment_loop_v1/run.py'))
MODES=('backoff','periodic4','classical_learner','ocn_hamilton','ocn_real')

@dataclass(frozen=True)
class Tuning:
    bounded_latency: bool = False
    backlog_credit: bool = False

class SchedulerAgent(CompactAgent):
    def __init__(self,*args,scheduler='backoff',tuning=Tuning(),**kwargs):
        super().__init__(*args,**kwargs)
        self.scheduler=scheduler;self.tuning=tuning
        self.emission_model=Predictor(scheduler) if scheduler in MODES[2:] else None
        self.births=[];self.last_attempt=0;self.refusal_ema=0.;self.choices=[];self.debt_trace=[];self.delays=[]
    def replace_memory(self,field,source,value,n):
        old=getattr(self,field)[source]
        super().replace_memory(field,source,value,n)
        if old!=value:self.births.append(n)
    def emit_pending(self,n,tools):
        state=self.retirement
        if not state['pending'] or self.emission_room(tools)<1:
            return super().emit_pending(n,tools)
        oldest=n-self.births[0];elapsed=n-self.last_attempt
        z=np.array([min(1.,sum(e['count'] for e in state['pending'])/8),
                    min(1.,elapsed/16),state['pressure'],self.refusal_ema])
        prediction=None;gain=None
        if self.scheduler=='backoff':emit=n>=state['retry_after']
        elif self.scheduler=='periodic4':emit=elapsed>=4
        else:
            prediction=self.emission_model.predict(z)[0]+np.array([.5,0.,0.,0.])
            probability=float(np.clip(prediction[0],0,1))
            credit=sum(e['count'] for e in state['pending']) if self.tuning.backlog_credit else state['pending'][0]['count']
            gain=probability*min(1.,credit/8)*(1+min(oldest,32)/16)
            emit=gain >= .10+.15*(1-probability) or elapsed>=(8 if self.tuning.bounded_latency else 16)
        protected=self.emission_model is not None and n<state['retry_after']
        if protected:emit=False
        choice=dict(step=n,protected=protected,retry_before=state['retry_after'],emit=bool(emit),oldest=oldest,elapsed=elapsed,features=z.tolist(),gain=gain)
        self.choices.append(choice)
        if not emit:
            self.last_emissions=[]
            return
        if self.scheduler=='periodic4':state['retry_after']=n;state['backoff']=1
        before=state['accepted_events'];calls=len(tools.calls)
        super().emit_pending(n,tools)
        if len(tools.calls)==calls:return
        if self.tuning.bounded_latency:
            # Cap our own retry policy, not a deadline issued by the environment.
            state['retry_after']=min(state['retry_after'],n+8)
            state['backoff']=min(state['backoff'],8)
        self.last_attempt=n
        accepted=state['accepted_events']-before
        self.delays.extend(n-b for b in self.births[:accepted]);del self.births[:accepted]
        refused=any(r.get('accepted') is False for r in self.last_emissions)
        self.refusal_ema=.8*self.refusal_ema+.2*float(refused)
        if prediction is not None:
            target=np.array([float(accepted>0),state['pressure'],float(refused),min(1.,len(self.births)/8)])
            self.emission_model.update(z,0,target,prediction)
        choice.update(released=accepted,refused=refused)
    def step(self,n,tools):
        result=super().step(n,tools)
        state=self.retirement
        assert len(self.births)==state['retired_events']-state['accepted_events']
        self.debt_trace.append(dict(step=n,debt=len(self.births),oldest=n-self.births[0] if self.births else 0))
        return result
