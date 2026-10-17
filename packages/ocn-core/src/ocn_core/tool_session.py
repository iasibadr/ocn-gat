"""Bounded multi-source aggregation session for a trusted model host. No model calls."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from .controller import Fault
from .checkpoint import save_checkpoint
from .controller import parse
from .task import TaskSpec


class ToolSession:
    def __init__(self, agent, tools, step, max_decisions=6, task=None, request_id=None, *, stage_metadata=False):
        if type(stage_metadata) is not bool:
            raise ValueError('Metadata staging must be boolean')
        if stage_metadata and not agent.dna.require_schema_binding:
            raise ValueError('Metadata staging requires schema binding')
        self._stage_metadata = stage_metadata
        self._candidate_paths = {}
        self._candidate_descriptors = {}
        task=TaskSpec("sum",agent.dna.source_ids) if task is None else task
        if type(task) is not TaskSpec or not set(task.sources)<=set(agent.dna.source_ids):
            raise ValueError("Task exceeds DNA permissions")
        if request_id is not None:
            from .receipt import validate_request_id
            validate_request_id(request_id)
            previous=getattr(agent,'_task_receipt',None)
            if previous is not None and previous['request_id']==request_id:
                raise ValueError('Request already committed; recover its receipt')
        self._request_id=request_id
        self._task=task
        if type(max_decisions) is not int or not 1 <= max_decisions <= 1024:
            raise ValueError("Invalid decision limit")
        if agent.policy != "reactive":
            raise ValueError("Tool sessions require reactive storage")
        if hasattr(agent, "retirement") and getattr(agent.dna, "emission_phase", None) != "after":
            raise ValueError("Tool sessions require after-task compact dissipation")
        if getattr(agent, "_tool_session", None) is not None or getattr(agent, "_tool_session_failed", False):
            raise ValueError("Active or failed tool session; finish or reload checkpoint")
        if type(step) is not int or step <= agent.last_step:
            raise ValueError('Steps must increase')
        if asdict(tools.dna) != asdict(agent.dna) or tools.calls or tools.cost:
            raise ValueError('Fresh matching tools required')
        if getattr(agent, '_pending_maintenance', None) is not None:
            raise ValueError('Unfinished maintenance')
        agent.before_request(step, tools)
        agent.last_step = step
        agent._tool_session = self
        self.closed = False
        self.decisions = 0
        self.max_decisions = max_decisions
        self.agent, self.tools, self.step = agent, tools, step
        self.verified = {}
        self.terminal_errors = {}
        self.done = False
        self.answer = None
        self.refused = False

    @property
    def request_id(self):
        return self._request_id

    @property
    def task(self):
        return self._task

    def execute(self, action):
        if self.closed or self.agent._tool_session is not self:
            raise ValueError("Session is closed or no longer owns the agent")
        if self.done:
            raise ValueError('Session already finished')
        if self.decisions >= self.max_decisions:
            return dict(ok=False,error='decision_budget')
        self.decisions += 1
        if (type(action) is not dict or set(action) not in ({'op','path','value'}, {'op','path','value','source'})
                or type(action['path']) is not str
                or type(action['value']) is not int
                or action['op'] not in ('read','locate','describe','evaluate','finish','abstain')):
            return dict(ok=False,error='invalid_action')
        op=action['op']; agent=self.agent
        source=action.get('source', self.task.sources[0] if len(self.task.sources)==1 else '')
        if type(source) is not str:
            return dict(ok=False,error='invalid_action')
        if op not in ('evaluate','finish','abstain') and source not in self.task.sources:
            return dict(ok=False,error='denied_source')
        if op in ('evaluate','finish','abstain') and source and source not in self.task.sources:
            return dict(ok=False,error='denied_source')
        if op=='evaluate':
            if action['path'] or action['value'] != 0:
                return dict(ok=False,error='invalid_action')
            if set(self.verified) != set(self.task.sources):
                return dict(ok=False,error='missing_evidence',
                    missing_sources=[s for s in self.task.sources if s not in self.verified])
            try:
                self.tools.charge('evaluate',self.task.operation)
            except Fault as error:
                return dict(ok=False,error=error.code)
            return dict(ok=True,result=self.task.evaluate(self.verified))
        if op=='finish':
            if set(self.verified) != set(self.task.sources) or action['value'] != self.task.evaluate(self.verified):
                return dict(ok=False,error='unverified_answer',
                    reason='missing_evidence' if set(self.verified) != set(self.task.sources) else 'task_mismatch',
                    task=dict(operation=self.task.operation,sources=list(self.task.sources)),
                    verified_inputs=[dict(source=s,value=self.verified[s]) for s in self.task.sources if s in self.verified],
                    missing_sources=[s for s in self.task.sources if s not in self.verified])
            self.done=True; self.answer=self.task.evaluate(self.verified)
            return dict(ok=True,value=self.answer)
        if op=='abstain':
            if not self.terminal_errors:
                return dict(ok=False,error='unjustified_abstention')
            self.done=True; self.refused=True
            return dict(ok=True,error=next(self.terminal_errors[s] for s in self.task.sources if s in self.terminal_errors))
        # New observations invalidate only the selected source's evidence.
        self.verified.pop(source,None); self.terminal_errors.pop(source,None)
        try:
            if op=='locate':
                value=self.tools.locate(source)
                if self._stage_metadata:
                    self._candidate_paths[source] = value
                else:
                    agent.replace_memory('paths',source,value,self.step)
                    agent.last_refresh[source]=self.step
            elif op=='describe':
                value=self.tools.describe(source)
                if (type(value) is not dict or set(value) != {'codec','value_path'}
                        or type(value['codec']) is not str or not value['codec'] or len(value['codec'])>128
                        or type(value['value_path']) is not list or not 1<=len(value['value_path'])<=16
                        or any(type(x) is not str or len(x)>4096 for x in value['value_path'])):
                    raise Fault('invalid_descriptor')
                if self._stage_metadata:
                    self._candidate_descriptors[source] = deepcopy(value)
                else:
                    agent.replace_memory('descriptors',source,value,self.step)
                    agent.last_refresh[source]=self.step
                if value['codec'] not in agent.dna.allowed_codecs:
                    raise Fault('unsupported')
            else:
                doc=self.tools.read(action['path'])
                descriptor=self._candidate_descriptors.get(source,agent.descriptors[source])
                value=parse(doc,source,self.step,descriptor,
                            agent.dna.allowed_codecs,agent.dna.require_schema_binding)
                if self._stage_metadata:
                    # Promote only metadata actually exercised by this verified read.
                    promoted = False
                    if self._candidate_paths.get(source) == action['path']:
                        agent.replace_memory('paths',source,self._candidate_paths.pop(source),self.step)
                        promoted = True
                    if source in self._candidate_descriptors:
                        agent.replace_memory('descriptors',source,self._candidate_descriptors.pop(source),self.step)
                        promoted = True
                    if promoted:
                        agent.last_refresh[source]=self.step
                self.verified[source]=value
            return dict(ok=True,result=value)
        except Fault as error:
            if error.code not in ('schema','not_found','unavailable'):
                self.terminal_errors[source]=error.code
            return dict(ok=False,error=error.code)

    def persist(self, path):
        """Close exactly once, including an unfinished decision sequence.

        After a persistence error discard this agent and reload its checkpoint.
        A verified finish is provisional until this method succeeds.
        """
        if self.closed or self.agent._tool_session is not self:
            raise ValueError('Session already closed')
        location=Path(path).resolve()
        root=self.tools.root.resolve()
        if location==root or root in location.parents:
            raise ValueError('Checkpoint must be outside the habitat')
        if hasattr(self.tools, 'reservoir') and location==Path(self.tools.reservoir.path).resolve():
            raise ValueError('Checkpoint must be separate from reservoir')
        self._candidate_paths.clear()
        self._candidate_descriptors.clear()
        self.closed = True
        self.agent._tool_session = None
        result=dict(answer=self.answer,refused=self.refused,done=self.done,cost=self.tools.cost,
                    decisions=self.decisions,task=asdict(self.task))
        try:
            if self.request_id is not None:
                from .receipt import receipt_for_session
                self.agent._task_receipt=receipt_for_session(self)
            if hasattr(self.agent,'retirement'):
                self.agent._pending_maintenance=(self.step,self.tools,result)
                return self.agent.finish_request(self.step,self.tools,path)
            save_checkpoint(self.agent,path)
            return result
        except Exception:
            self.agent._tool_session_failed = True
            raise
