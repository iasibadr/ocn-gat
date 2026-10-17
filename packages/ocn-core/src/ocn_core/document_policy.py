"""Opt-in host-evaluated policy selection using existing experience memory.

One live owner; no process-resume protocol, autonomous evaluator or quaternion
claim. Each action is a whole primary/fallback policy with immutable revisions.
"""
from copy import deepcopy
import hashlib
import json
from threading import RLock
from .document_session import DocumentSession
from .document_feedback import FeedbackDocumentSession
from .experience_memory import ExperienceMemory,label


class PolicyDocumentSession:
    def __init__(self,routes,memory_path,*,policies,context,evaluate,evaluation_contract,
                 max_model_calls=8,max_requests=32,probe_every=4,attempt_budget=None,
                 route_policy='sticky'):
        label(evaluation_contract)
        if type(policies) is not dict or not 1<=len(policies)<=8:
            raise ValueError('One to eight policies required')
        for name,spec in policies.items():
            label(name)
            if type(spec) is not tuple or len(spec)!=4 or not callable(spec[0]) or not callable(spec[2]):
                raise ValueError('Policy requires primary, revision, fallback, revision')
            label(spec[1]);label(spec[3])
        if not callable(context) or not callable(evaluate):raise ValueError('Trusted context and evaluator required')
        if type(probe_every) is not int or not 2<=probe_every<=32:raise ValueError('Probe interval must be 2..32')
        self._policies=dict(policies);self.names=tuple(policies);self.selected=None
        self.context=context;self.probe_every=probe_every;self.step=0;self.probe_cursor=0
        self.attempted={};self.lock=RLock()
        def primary(*args):return self._policies[self.selected][0](*args)
        def fallback(*args):return self._policies[self.selected][2](*args)
        def revision(index):return json.dumps([self.selected,self._policies[self.selected][index]])
        self.session=DocumentSession(routes,primary,lambda:revision(1),fallback_worker=fallback,
            fallback_revision=lambda:revision(3),max_model_calls=max_model_calls,max_requests=max_requests,
            attempt_budget=attempt_budget,route_policy=route_policy)
        contract=hashlib.sha256(json.dumps([evaluation_contract,self.session.adapter.pinned,
            [(n,policies[n][1],policies[n][3]) for n in self.names]],sort_keys=True).encode()).hexdigest()
        self.memory=ExperienceMemory.create(memory_path,contract_id=contract,actions=list(self.names),capacity=max_requests)
        self.bridges={name:FeedbackDocumentSession(self.session,self.memory,action=name,
            context=context,evaluate=evaluate) for name in self.names}

    def answer(self,request):
        with self.lock:
            if any(b.pending is not None for b in self.bridges.values()):
                raise RuntimeError('Verified feedback pending; retry before selection')
            if self.step>=self.session.max_requests or self.session.requests>=self.session.max_requests:
                raise RuntimeError('Session request budget exhausted')
            request=deepcopy(request);context=label(self.context(deepcopy(request)))
            estimates={n:self.memory.estimate(context,n) for n in self.names}
            counts=self.attempted.get(context,{n:0 for n in self.names})
            unknown=[n for n in self.names if estimates[n]['observations']==0]
            if unknown:
                chosen=min(unknown,key=lambda n:counts[n]);reason='unobserved_policy_probe'
            elif self.step%self.probe_every==0:
                chosen=self.names[self.probe_cursor%len(self.names)]
                self.probe_cursor+=1;reason='scheduled_probe'
            else:
                chosen=max(self.names,key=lambda n:estimates[n]['expected_return']);reason='observed_reward'
            self.selected=chosen
            bridge=self.bridges[chosen];bridge.context=lambda _:context
            # Bound selection attempts even when execution/evaluation raises.
            self.step+=1;counts[chosen]+=1;self.attempted[context]=counts
            result=bridge.answer(request)
            return dict(result,selection=dict(policy=chosen,reason=reason,estimates=estimates,
                step=self.step,algorithm='verified_success_ewma_with_periodic_probes'))

    def retry_feedback(self):
        with self.lock:
            pending=[b for b in self.bridges.values() if b.pending is not None]
            if len(pending)!=1:raise ValueError('Exactly one pending feedback required')
            return pending[0].retry_feedback()
