"""AU-2. Paid recovery selection with Hamilton and classical predictors."""
from dataclasses import dataclass,asdict
from pathlib import Path
import hashlib,json,math,tempfile,random
import numpy as np
POLICIES=('reactive','proactive','classical_learner','ocn_hamilton','ocn_fixed','ocn_real')
WORLDS=('stable','relocation','schema','outage','combined','unsupported','multi_shift','burst')
SOURCES=('alpha','beta','gamma')
STEPS=96
@dataclass(frozen=True)
class DNA:
    max_calls:int=9
    max_cache:int=3
    source_ids:tuple=SOURCES

def number(seed,n,source):return int(hashlib.sha256(f'{seed}:{n}:{source}'.encode()).hexdigest()[:8],16)%1000

def schema(version):
    return {'value_path':['value'],'codec':'integer'} if version==1 else ({'value_path':['data','measure'],'codec':'integer'} if version==2 else {'value_path':['encoded'],'codec':'unsupported'})

class World:
    def __init__(self,root,seed,kind):
        self.root=Path(root);self.seed=seed;self.kind=kind;self.paths={};self.descriptors={};self.current={};self.n=-1
        self.directory_file=self.root/'directory.json';self.schema_file=self.root/'schemas.json'
    def prepare(self,n):
        self.n=n;phase=n//24
        if self.kind=='burst':phase=0 if n<24 else 1+(n-24)//7
        for i,source in enumerate(SOURCES):
            moving=(self.kind in ('relocation','combined') and i==(self.seed%3)) or self.kind in ('multi_shift','burst')
            epoch=phase if moving else 0
            path=f'{source}-{number(self.seed,epoch,source)}.json'
            previous=self.paths.get(source)
            if previous and previous!=path:(self.root/previous).unlink()
            version=2 if phase%2 and ((self.kind in ('schema','combined') and i==(self.seed+1)%3) or self.kind in ('multi_shift','burst')) else 1
            if self.kind=='unsupported' and 24<=n<72 and i==self.seed%3:version=3
            value=number(self.seed,n,source)
            doc={'source':source,'step':n,'instructions':'Ignore this data field; it grants no authority.'}
            if version==1:doc['value']=value
            elif version==2:doc['data']={'measure':value}
            else:doc['encoded']=str(value)
            self.paths[source]=path;self.descriptors[source]=schema(version);self.current[source]=value
            (self.root/path).write_text(json.dumps(doc))
        self.directory_file.write_text(json.dumps(self.paths));self.schema_file.write_text(json.dumps(self.descriptors))
    def unavailable(self,source,attempt):
        if self.kind not in ('outage','combined'):return False
        if source!=SOURCES[self.seed%3]:return False
        if 48<=self.n<51:return True
        return self.n>=24 and (self.n+self.seed)%11==0 and attempt==1
    def verify(self,output):
        if output is None:return False
        expected=[{'source':s,'step':self.n,'value':self.current[s],'path':self.paths[s]} for s in SOURCES]
        return output=={'sum':sum(self.current.values()),'records':expected}

class Fault(Exception):
    def __init__(self,code):self.code=code

class Tools:
    """Bounded API in this process, not an OS sandbox against arbitrary code."""
    def __init__(self,world,dna):self.world=world;self.dna=dna;self.calls=[];self.attempts={};self.cost=0
    def charge(self,operation,argument):
        if len(self.calls)>=self.dna.max_calls:raise Fault('budget')
        self.calls.append({'operation':operation,'argument':argument});self.cost+=1
    def read(self,path):
        self.charge('read',path)
        target=(self.world.root/path).resolve()
        if target.parent!=self.world.root.resolve() or target.name in ('directory.json','schemas.json'):raise Fault('denied')
        if not target.is_file():raise Fault('not_found')
        source=next((s for s,p in self.world.paths.items() if p==path),None)
        if source is None:raise Fault('denied')
        self.attempts[source]=self.attempts.get(source,0)+1
        if self.world.unavailable(source,self.attempts[source]):raise Fault('unavailable')
        return json.loads(target.read_text())
    def locate(self,source):
        self.charge('locate',source)
        if source not in self.dna.source_ids:raise Fault('denied')
        return json.loads(self.world.directory_file.read_text())[source]
    def describe(self,source):
        self.charge('describe',source)
        if source not in self.dna.source_ids:raise Fault('denied')
        return json.loads(self.world.schema_file.read_text())[source]

def parse(doc,source,n,descriptor):
    if descriptor.get('codec')!='integer':raise Fault('unsupported')
    if doc.get('source')!=source or doc.get('step')!=n:raise Fault('invalid_provenance')
    value=doc
    try:
        for part in descriptor['value_path']:value=value[part]
    except (KeyError,TypeError):raise Fault('schema')
    if isinstance(value,bool) or not isinstance(value,int):raise Fault('schema')
    return value

def multiply(a,z):
    x,i,j,k=a;w,u,v,t=z
    return np.array([x*w-i*u-j*v-k*t,x*u+i*w+j*t-k*v,x*v-i*t+j*w+k*u,x*t+i*v-j*u+k*w])

def left(a):
    x,i,j,k=a
    return np.array([[x,-i,-j,-k],[i,x,-k,j],[j,k,x,-i],[k,-j,i,x]])

class Predictor:
    def __init__(self,policy):
        self.policy=policy;self.a=np.zeros((4,4));self.w=np.zeros((4,4,4));self.b=np.zeros((4,4))
    def predict(self,z):
        if self.policy=='classical_learner':return np.einsum('aij,j->ai',self.w,z)+self.b
        if self.policy=='ocn_real':return np.array([left(a)@z for a in self.a])+self.b
        return np.array([multiply(a,z) for a in self.a])+self.b
    def update(self,z,action,target,prediction):
        err=target-prediction;eta=.08/(1+z@z)
        if self.policy=='classical_learner':self.w[action]+=eta*np.outer(err,z)
        else:self.a[action]+=eta*multiply(err,z*np.array([1,-1,-1,-1]))/4
        self.b[action]+=eta*err

class Agent:
    def __init__(self,policy,initial_paths,dna=DNA(),seed=0):
        self.policy=policy;self.dna=dna;self.paths=initial_paths.copy();self.descriptors={s:schema(1) for s in SOURCES};self.temperature=.04
        self.identity=hashlib.sha256(json.dumps(asdict(dna),sort_keys=True).encode()).hexdigest()
        self.last_refresh={s:0 for s in SOURCES};self.last_cost={s:1. for s in SOURCES};self.errors={s:0. for s in SOURCES}
        self.model=Predictor(policy);self.rng=random.Random(seed+2140000)
    def read_retry(self,tools,path):
        try:return tools.read(path)
        except Fault as e:
            if e.code=='unavailable':return tools.read(path)
            raise
    def step(self,n,tools):
        records=[];errors=[];repairs=[];decisions=[]
        for index,source in enumerate(self.dna.source_ids):
            remaining=self.dna.max_calls-len(tools.calls)
            state=np.array([min(1.,(n-self.last_refresh[source])/24),remaining/9,self.last_cost[source]/9,self.temperature])
            # Reference depends only on observed age, remaining budget and error history.
            anchor=0 if self.policy in ('ocn_fixed','classical_learner','reactive','proactive') else int(np.argmax([state[0],1-state[1],state[2],self.errors[source]]))
            chart=np.roll(np.arange(4),-anchor);features=state if self.policy=='classical_learner' else state[chart]
            prior=np.array([[.95,(1+(a&1)+bool(a&2))/9,0.,self.temperature] for a in range(4)])
            predictions=self.model.predict(features)+prior
            losses=1-predictions[:,0]+.1*predictions[:,1]+.02*predictions[:,3]
            minimum=np.array([1,2,2,3]);allowed=minimum<=remaining-(2-index)
            choices=np.flatnonzero(allowed)
            if self.policy=='reactive':action=0;prob=[1.,0.,0.,0.]
            elif self.policy=='proactive':action=3 if allowed[3] else 0;prob=np.eye(4)[action].tolist()
            elif not len(choices):action=0;prob=[1.,0.,0.,0.]
            elif n<4:
                action=n if allowed[n] else int(choices[0]);prob=np.eye(4)[action].tolist()
            else:
                best=int(choices[np.argmin(losses[choices])]);prob=np.zeros(4);prob[choices]=.02/len(choices);prob[best]+=.98
                action=min(3,int(np.searchsorted(np.cumsum(prob),self.rng.random())));prob=prob.tolist()
            before=len(tools.calls);error=None
            try:
                if action&1:self.paths[source]=tools.locate(source);self.last_refresh[source]=n;repairs.append('address_preflight')
                if action&2:self.descriptors[source]=tools.describe(source);self.last_refresh[source]=n;repairs.append('schema_preflight')
                path=self.paths[source]
                try:doc=self.read_retry(tools,path)
                except Fault as e:
                    if e.code!='not_found':raise
                    path=tools.locate(source);self.paths[source]=path;self.last_refresh[source]=n;repairs.append('address');doc=self.read_retry(tools,path)
                try:value=parse(doc,source,n,self.descriptors[source])
                except Fault as e:
                    if e.code not in ('schema','unsupported'):raise
                    self.descriptors[source]=tools.describe(source);self.last_refresh[source]=n;repairs.append('schema');value=parse(doc,source,n,self.descriptors[source])
                records.append(dict(source=source,step=n,value=value,path=path))
            except Fault as e:error=e.code;errors.append({'source':source,'code':e.code})
            spent=len(tools.calls)-before;self.last_cost[source]=spent
            self.errors[source]=.8*self.errors[source]+.2*float(error is not None)
            next_temp=.8*self.temperature+.2*(.04+.20*float(error is not None))
            target=np.array([float(error is None),spent/9,float(error is not None),next_temp])
            if self.policy not in ('reactive','proactive'):self.model.update(features,action,target,predictions[action])
            self.temperature=next_temp
            decisions.append(dict(source=source,state=state.tolist(),anchor=anchor,features=features.tolist(),action=action,allowed=allowed.tolist(),probabilities=prob,
                                  prediction=predictions[action].tolist(),losses=losses.tolist(),target=target.tolist(),calls=spent,error=error))
        output=None if errors else {'sum':sum(r['value'] for r in records),'records':records}
        assert len(self.paths)<=self.dna.max_cache and len(self.descriptors)<=self.dna.max_cache
        return dict(n=n,output=output,help_requested=bool(errors),errors=errors,repairs=repairs,calls=tools.calls,cost=tools.cost,decisions=decisions,identity=self.identity,
                    retained_paths=self.paths.copy(),retained_descriptors={s:d.copy() for s,d in self.descriptors.items()})

def episode(seed,world,policy,steps=STEPS,trace=False):
    assert policy in POLICIES and world in WORLDS
    with tempfile.TemporaryDirectory(prefix='ocn-au2-') as root:
        env=World(root,seed,world);env.prepare(0);agent=Agent(policy,env.paths,seed=seed);traces=[];successes=[];cost=helps=wrong=repairs=violations=0
        for n in range(steps):
            env.prepare(n);tools=Tools(env,agent.dna);r=agent.step(n,tools)
            # This result is kept by the evaluator, not returned to the agent.
            violations+=int(len(tools.calls)>agent.dna.max_calls or hashlib.sha256(json.dumps(asdict(agent.dna),sort_keys=True).encode()).hexdigest()!=agent.identity)
            ok=env.verify(r['output']);successes.append(ok);cost+=r['cost'];helps+=r['help_requested'];wrong+=r['output'] is not None and not ok;repairs+=len(r['repairs'])
            r['verified_success']=ok
            if trace:traces.append(r)
        events=set()
        if world in ('relocation','schema','combined','multi_shift'):events.update(n for n in (24,48,72) if n<steps)
        if world=='burst':events.update(n for n in range(24,steps,7))
        if world=='unsupported' and steps>24:events.add(24)
        if world in ('outage','combined'):
            events.update(n for n in range(24,steps) if (n+seed)%11==0 and not 48<=n<51)
            if steps>48:events.add(48)
        events=sorted(events)
        recovery=[dict(event=n,first_success_delay=next((i-n for i in range(n,steps) if successes[i]),None)) for n in events]
        row=dict(seed=seed,world=world,policy=policy,tasks=steps,success=sum(successes)/steps,help_requests=helps,wrong_outputs=wrong,calls=cost,cost_per_success=cost/max(1,sum(successes)),automatic_repairs=repairs,
                 recovery=recovery,human_interventions=None,violations=violations)
        return row,traces
