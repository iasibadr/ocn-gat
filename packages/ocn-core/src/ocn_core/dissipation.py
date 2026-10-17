"""Opt-in information retirement and observed environmental backpressure.

This is an engineering queue, not a model of physical heat or entropy.
"""
from dataclasses import dataclass
import hashlib
import json
import uuid
from .controller import Agent, DNA, Fault

@dataclass(frozen=True)
class DissipativeDNA(DNA):
    retirement_capacity: int = 8
    emission_limit: int = 2

    def __post_init__(self):
        super().__post_init__()
        if type(self.retirement_capacity) is not int or not 1 <= self.retirement_capacity <= 1024:
            raise ValueError('Invalid retirement capacity')
        if type(self.emission_limit) is not int or not 1 <= self.emission_limit <= self.max_calls:
            raise ValueError('Invalid emission limit')

class DissipativeAgent(Agent):
    def __init__(self,policy,initial_paths,dna,seed=0):
        if not isinstance(dna,DissipativeDNA):raise ValueError('Dissipative DNA required')
        super().__init__(policy,initial_paths,dna,seed)
        self.retirement=dict(stream=uuid.uuid4().hex,sequence=0,pending=[],accepted=0,
                             pressure=0.,retry_after=0,backoff=1)
        self.last_emissions=[]

    def replace_memory(self,field,source,value,n):
        old=getattr(self,field)[source]
        if old == value:return
        state=self.retirement
        if len(state['pending']) >= self.dna.retirement_capacity:
            raise Fault('retirement_full')
        # Old contents leave active memory. Only a fingerprint enters the queue;
        # it cannot be decoded or retrieved by the predictor.
        digest=hashlib.sha256(json.dumps(dict(field=field,source=source,old=old,new=value),sort_keys=True).encode()).hexdigest()
        state['sequence']+=1
        state['pending'].append(dict(sequence=state['sequence'],digest=digest))
        super().replace_memory(field,source,value,n)

    def prepare_emission(self,event):
        pass

    def emission_room(self,tools):
        return max(0,min(self.dna.max_calls-len(self.dna.source_ids),self.dna.max_calls-len(tools.calls)))

    def before_request(self,n,tools):
        self.last_emissions=[]
        state=self.retirement
        if n < state['retry_after']:return
        # Reserve one read per source. Emissions share the task's total budget.
        room=self.emission_room(tools)
        for _ in range(min(room,self.dna.emission_limit,len(state['pending']))):
            event=state['pending'][0]
            self.prepare_emission(event)
            try:
                receipt=tools.dissipate(state['stream'],event)
            except Fault as exc:
                self.last_emissions.append(dict(status=exc.code,sequence=event['sequence']))
                state['retry_after']=n+state['backoff'];state['backoff']=min(32,state['backoff']*2)
                break
            if type(receipt) is not dict or set(receipt)!= {'accepted','pressure'} or type(receipt['accepted']) is not bool or type(receipt['pressure']) not in (int,float) or not 0 <= receipt['pressure'] <= 1:
                raise ValueError('Invalid dissipation receipt')
            state['pressure']=float(receipt['pressure'])
            self.last_emissions.append(dict(sequence=event['sequence'],**receipt))
            if not receipt['accepted']:
                state['retry_after']=n+state['backoff'];state['backoff']=min(32,state['backoff']*2)
                break
            state['pending'].pop(0);state['accepted']+=1;state['backoff']=1;state['retry_after']=n+1

    def step(self,n,tools):
        if not callable(getattr(tools,'dissipate',None)):
            raise ValueError('Dissipative habitat required')
        result=super().step(n,tools)
        result['dissipation']=dict(pending=len(self.retirement['pending']),accepted=self.retirement['accepted'],
                                   pressure=self.retirement['pressure'],receipts=self.last_emissions)
        return result
