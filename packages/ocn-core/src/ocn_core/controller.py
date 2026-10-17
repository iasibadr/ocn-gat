"""Bounded recovery controller, extracted from sealed AU-2.

Numerical state is an operational proxy, not physical thermodynamics.
"""
from dataclasses import dataclass, asdict
import hashlib, json, random
import numpy as np
POLICIES = ('reactive','proactive','classical_learner','ocn_hamilton','ocn_fixed','ocn_real')
@dataclass(frozen=True)
class DNA:
    max_calls: int = 9
    max_cache: int = 3
    source_ids: tuple = ('alpha','beta','gamma')
    allowed_codecs: tuple = ('integer',)
    require_schema_binding: bool = False

    def __post_init__(self):
        if type(self.require_schema_binding) is not bool:
            raise ValueError('Schema binding requirement must be boolean')
        if (type(self.allowed_codecs) is not tuple or not self.allowed_codecs
                or any(c not in ('integer','decimal_integer') for c in self.allowed_codecs)
                or len(set(self.allowed_codecs)) != len(self.allowed_codecs)):
            raise ValueError('Invalid allowed codecs')
        if type(self.max_calls) is not int or self.max_calls < len(self.source_ids):
            raise ValueError('Budget must permit one read per source')
        if type(self.source_ids) is not tuple or not self.source_ids or any(type(x) is not str or not x for x in self.source_ids) or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError('Source IDs must be a nonempty tuple of unique strings')
        if type(self.max_cache) is not int or self.max_cache < len(self.source_ids):
            raise ValueError('Cache must hold one entry per source')

def schema(version):
    return {'value_path':['value'],'codec':'integer'} if version == 1 else {'value_path':['data','measure'],'codec':'integer'}

class Fault(Exception):
    def __init__(self,code):self.code=code

def descriptor_digest(descriptor):
    """Content binding supplied by a trusted producer, not authentication."""
    return hashlib.sha256(json.dumps(descriptor, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()

def parse(doc,source,n,descriptor,allowed_codecs=('integer',),require_schema_binding=False):
    if require_schema_binding and 'schema_digest' not in doc:
        raise Fault('missing_schema_binding')
    if 'schema_digest' in doc:
        digest=doc['schema_digest']
        if (type(digest) is not str or len(digest)!=64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise Fault('invalid_schema_binding')
        if digest != descriptor_digest(descriptor):raise Fault('schema')
    codec=descriptor.get('codec')
    if codec not in allowed_codecs:raise Fault('unsupported')
    if (type(doc.get('source')) is not str or doc.get('source')!=source
            or type(doc.get('step')) is not int or doc.get('step')!=n):
        raise Fault('invalid_provenance')
    value=doc
    try:
        for part in descriptor['value_path']:value=value[part]
    except (KeyError,TypeError):raise Fault('schema')
    if codec=='decimal_integer':
        # Canonical ASCII signed decimal, bounded before conversion.
        import re
        if type(value) is not str or len(value)>128 or re.fullmatch(r'(?:0|-[1-9][0-9]*|[1-9][0-9]*)',value) is None:
            raise Fault('schema')
        value=int(value)
    elif codec!='integer':raise Fault('unsupported')
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
        # Preserve scalar Hamilton operation order while allocating one result array.
        w,u,v,t=z
        return np.array([[x*w-i*u-j*v-k*t,x*u+i*w+j*t-k*v,
                          x*v-i*t+j*w+k*u,x*t+i*v-j*u+k*w]
                         for x,i,j,k in self.a])+self.b
    def update(self,z,action,target,prediction):
        err=target-prediction;eta=.08/(1+z@z)
        if self.policy=='classical_learner':self.w[action]+=eta*np.outer(err,z)
        else:self.a[action]+=eta*multiply(err,z*np.array([1,-1,-1,-1]))/4
        self.b[action]+=eta*err

class Agent:
    def __init__(self,policy,initial_paths,dna=DNA(),seed=0):

        if policy not in POLICIES: raise ValueError('Unknown policy')
        if set(initial_paths) != set(dna.source_ids): raise ValueError('Initial paths must match DNA sources')
        self.policy=policy;self.dna=dna;self.paths=initial_paths.copy();self.descriptors={s:schema(1) for s in dna.source_ids};self.temperature=.04
        self.identity=hashlib.sha256(json.dumps(asdict(dna),sort_keys=True).encode()).hexdigest()
        self.last_refresh={s:0 for s in dna.source_ids};self.last_cost={s:1. for s in dna.source_ids};self.errors={s:0. for s in dna.source_ids}
        self.capture_sensitivities=False
        self.model=Predictor(policy);self.rng=random.Random(seed+2140000);self.last_step=-1
    def read_retry(self,tools,path):
        try:return tools.read(path)
        except Fault as e:
            if e.code=='unavailable':return tools.read(path)
            raise
    def predictor_for(self,source):
        return self.model

    def temperature_for(self,source):
        return self.temperature

    def record_temperature(self,source,value):
        self.temperature=value

    def action_mask(self,source,allowed):
        return allowed

    def choose_action(self,n,allowed,losses):
        choices=np.flatnonzero(allowed)
        if self.policy=='reactive':action=0;prob=[1.,0.,0.,0.]
        elif self.policy=='proactive':action=3 if allowed[3] else 0;prob=np.eye(4)[action].tolist()
        elif not len(choices):action=0;prob=[1.,0.,0.,0.]
        elif n<4:
            action=n if allowed[n] else int(choices[0]);prob=np.eye(4)[action].tolist()
        else:
            best=int(choices[np.argmin(losses[choices])]);prob=np.zeros(4);prob[choices]=.02/len(choices);prob[best]+=.98
            action=min(3,int(np.searchsorted(np.cumsum(prob),self.rng.random())));prob=prob.tolist()
        return action,prob

    def replace_memory(self, field, source, value, n):
        getattr(self, field)[source] = value

    def before_request(self, n, tools):
        pass

    def step(self,n,tools):
        if getattr(self, "_tool_session", None) is not None or getattr(self, "_tool_session_failed", False):
            raise ValueError("Active or failed tool session; finish or reload checkpoint")
        if type(n) is not int or n <= self.last_step:
            raise ValueError('Steps must be nonnegative and strictly increasing')
        if asdict(tools.dna) != asdict(self.dna) or tools.calls or tools.cost:
            raise ValueError('Use a fresh adapter with the same DNA for each request')
        self.last_step = n
        self.before_request(n, tools)
        records=[];errors=[];repairs=[];decisions=[]
        for index,source in enumerate(self.dna.source_ids):
            model=self.predictor_for(source);temperature=self.temperature_for(source)
            remaining=self.dna.max_calls-len(tools.calls)
            state=np.array([min(1.,(n-self.last_refresh[source])/24),remaining/self.dna.max_calls,self.last_cost[source]/self.dna.max_calls,temperature])
            # Reference depends only on observed age, remaining budget and error history.
            anchor=0 if self.policy in ('ocn_fixed','classical_learner','reactive','proactive') else int(np.argmax([state[0],1-state[1],state[2],self.errors[source]]))
            chart=np.roll(np.arange(4),-anchor);features=state if self.policy=='classical_learner' else state[chart]
            prior=np.array([[.95,(1+(a&1)+bool(a&2))/self.dna.max_calls,0.,temperature] for a in range(4)])
            predictions=model.predict(features)+prior
            losses=1-predictions[:,0]+.1*predictions[:,1]+.02*predictions[:,3]
            minimum=np.array([1,2,2,3]);allowed=minimum<=remaining-(len(self.dna.source_ids)-1-index)
            allowed=self.action_mask(source,allowed)
            action,prob=self.choose_action(n,allowed,losses)
            sensitivity=None
            if self.capture_sensitivities:
                from .sensitivities import prediction_jacobian,action_entropy
                # The prediction prior contributes +temperature to output coordinate 3.
                prior_jacobian=np.zeros((4,4));prior_jacobian[3,3]=1.
                order=(0,1,2,3) if self.policy=='classical_learner' else tuple(int(i) for i in chart)
                jacobian=prediction_jacobian(model,action,input_order=order,prior_jacobian=prior_jacobian)
                sensitivity=dict(jacobian=jacobian.tolist(),
                    conjugated_jacobian=(np.diag([1.,-1.,-1.,-1.])@jacobian).tolist(),
                    score_gradient=(-jacobian[0]+.1*jacobian[1]+.02*jacobian[3]).tolist(),
                    action_entropy_nats=action_entropy(prob),chart_frozen=True,
                    scope='frozen_predictor_before_update_not_environment_derivative')
            before=len(tools.calls);error=None
            try:
                if action&1:self.replace_memory("paths",source,tools.locate(source),n);self.last_refresh[source]=n;repairs.append('address_preflight')
                if action&2:self.replace_memory("descriptors",source,tools.describe(source),n);self.last_refresh[source]=n;repairs.append('schema_preflight')
                path=self.paths[source]
                try:doc=self.read_retry(tools,path)
                except Fault as e:
                    if e.code!='not_found':raise
                    path=tools.locate(source);self.replace_memory("paths",source,path,n);self.last_refresh[source]=n;repairs.append('address');doc=self.read_retry(tools,path)
                try:value=parse(doc,source,n,self.descriptors[source],self.dna.allowed_codecs,self.dna.require_schema_binding)
                except Fault as e:
                    if e.code not in ('schema','unsupported'):raise
                    self.replace_memory("descriptors",source,tools.describe(source),n);self.last_refresh[source]=n;repairs.append('schema');value=parse(doc,source,n,self.descriptors[source],self.dna.allowed_codecs,self.dna.require_schema_binding)
                records.append(dict(source=source,step=n,value=value,path=path))
            except Fault as e:error=e.code;errors.append({'source':source,'code':e.code})
            spent=len(tools.calls)-before;self.last_cost[source]=spent
            self.errors[source]=.8*self.errors[source]+.2*float(error is not None)
            next_temp=.8*temperature+.2*(.04+.20*float(error is not None))
            target=np.array([float(error is None),spent/self.dna.max_calls,float(error is not None),next_temp])
            if self.policy not in ('reactive','proactive'):model.update(features,action,target,predictions[action])
            self.record_temperature(source,next_temp)
            decisions.append(dict(source=source,state=state.tolist(),anchor=anchor,features=features.tolist(),action=action,allowed=allowed.tolist(),probabilities=prob,
                                  prediction=predictions[action].tolist(),losses=losses.tolist(),target=target.tolist(),calls=spent,error=error))
            if sensitivity is not None:decisions[-1]['sensitivities']=sensitivity
        output=None if errors else {'sum':sum(r['value'] for r in records),'records':records}
        assert len(self.paths)<=self.dna.max_cache and len(self.descriptors)<=self.dna.max_cache
        return dict(n=n,output=output,help_requested=bool(errors),errors=errors,repairs=repairs,calls=tools.calls,cost=tools.cost,decisions=decisions,identity=self.identity,
                    retained_paths=self.paths.copy(),retained_descriptors={s:d.copy() for s,d in self.descriptors.items()})
