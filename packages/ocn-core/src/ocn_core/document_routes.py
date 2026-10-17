"""Read-only exact-version routing facade for EvidenceAgent, experimental."""
from dataclasses import replace
import time
from .document_adapter import DocumentAdapter

class RouteAdapter(DocumentAdapter):
    # EvidenceAgent currently requires this type and uses only read(). Other
    # inherited host mutation APIs are explicitly disabled on this facade.
    def __init__(self,routes,*,policy='sticky',clock=time.monotonic):
        if type(routes) is not dict or not 1<=len(routes)<=4:raise ValueError('One to four host routes required')
        if policy not in ('fixed','sticky','hysteretic'):raise ValueError('Unknown route policy')
        if any(type(k) is not str or not k or '/' in k or len(k)>64 or not isinstance(v,DocumentAdapter) or isinstance(v,RouteAdapter) for k,v in routes.items()):
            raise ValueError('Named ordinary document adapters required')
        bindings=[a.bindings() for a in routes.values()]
        manifests=[{k:v['sha256'] for k,v in b.items()} for b in bindings]
        if not manifests[0] or any(m!=manifests[0] for m in manifests):raise ValueError('Routes must pin identical document versions')
        self.routes=dict(routes);self.pinned=dict(manifests[0]);self.preferred={};self.policy=policy;self.clock=clock;self.events=[]
        self.attempts=0;self.failures=0;self.switches=0;self.candidates={}

    def snapshot(self):
        """Bounded observations of route behavior; no document contents or paths."""
        return dict(policy=self.policy,preferred=dict(self.preferred),attempts=self.attempts,
                    failures=self.failures,switches=self.switches)

    def read(self,document_id,*,discovery_bytes=None):
        if document_id not in self.pinned:raise ValueError('Unknown document identifier')
        order=list(self.routes)
        if self.policy=='hysteretic' and document_id not in self.preferred:
            self.preferred[document_id]=order[0]
        if self.policy in ('sticky','hysteretic') and document_id in self.preferred:
            name=self.preferred[document_id];order.remove(name);order.insert(0,name)
        for name in order:
            start=self.clock();event=dict(document_id=document_id,route=name,status='failed');self.attempts+=1
            try:
                document=self.routes[name].read(document_id,discovery_bytes=discovery_bytes)
                if document.sha256!=self.pinned[document_id]:raise ValueError('Route changed host-pinned version')
            except (OSError,ValueError) as exc:
                self.failures+=1;event['error_type']=type(exc).__name__
            else:
                event['status']='value'
                if self.policy=='sticky':self.preferred[document_id]=name
                elif self.policy=='hysteretic':
                    preferred=self.preferred[document_id]
                    if name==preferred:self.candidates.pop(document_id,None)
                    else:
                        candidate,count=self.candidates.get(document_id,(None,0))
                        count=count+1 if candidate==name else 1
                        if count>=2:
                            self.preferred[document_id]=name;self.candidates.pop(document_id,None)
                            self.switches+=1
                        else:self.candidates[document_id]=(name,count)
                return replace(document,path=name+'/'+document.path,
                    relocated_from=None if document.relocated_from is None else name+'/'+document.relocated_from)
            finally:
                event['seconds']=max(0.,self.clock()-start);self.events.append(event);self.events=self.events[-32:]
        if self.policy=='hysteretic':self.candidates.pop(document_id,None)
        raise ValueError('Pinned version unavailable on all authorized routes')

    def bind(self,*args,**kwargs):raise ValueError('Enroll routes through host before constructing facade')
    def accept_version(self,*args,**kwargs):raise ValueError('Reconstruct facade for host-approved version changes')
    def bindings(self):return {k:dict(sha256=v) for k,v in self.pinned.items()}
    def validate_reference(self,document,quote):
        fresh=self.read(document.document_id)
        if fresh.sha256!=document.sha256 or not isinstance(quote,str) or not quote or quote not in fresh.text:
            raise ValueError('Reference not present in current pinned version')
        return fresh
