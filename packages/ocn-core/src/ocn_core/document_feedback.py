"""Host-evaluated mission feedback for the existing document session.

Opt-in bridge, not semantic verification or a strategy selector. The host must
retain returned receipts if it needs durable links to evaluation evidence.
Pending writes are in-process only; full crash recovery is not provided.
"""
from copy import deepcopy
import threading
import uuid

from .document_session import DocumentSession
from .experience_memory import ExperienceMemory, label
from .reward_selection import finite


class FeedbackDocumentSession:
    def __init__(self, session, memory, *, action, context, evaluate):
        if not isinstance(session, DocumentSession) or type(memory) is not ExperienceMemory:
            raise ValueError('Existing DocumentSession and ExperienceMemory required')
        label(action)
        if not callable(context) or not callable(evaluate):
            raise ValueError('Trusted host context and evaluator required')
        with memory.connect() as db:
            if action not in memory.metadata(db)['actions']:
                raise ValueError('Action must belong to experience contract')
        self.session, self.memory = session, memory
        self.action, self.context, self.evaluate = action, context, evaluate
        self.pending = None
        self.lock = threading.Lock()

    def _record(self):
        receipt, fact = self.pending
        self.memory.record(**fact)
        estimate = self.memory.estimate(fact['context'], fact['action'])
        self.pending = None
        return dict(receipt, feedback='recorded', estimate=estimate)

    def retry_feedback(self):
        """Retry the same verified observation; never call the worker again."""
        with self.lock:
            if self.pending is None:
                raise ValueError('No verified feedback pending')
            return self._record()

    def answer(self, request):
        with self.lock:
            if self.pending is not None:
                raise RuntimeError('Record pending feedback before another mission')
            request = deepcopy(request)
            # Context is supplied before execution, not derived from the answer.
            context = self.context(deepcopy(request))
            label(context)
            event = 'mission-' + uuid.uuid4().hex
            before = self.session.calls
            environment_before = self.session.adapter.snapshot()
            try:
                response = self.session.answer(**request)
                outcome = dict(status='returned', response=response)
            except (ValueError, RuntimeError, OSError) as exc:
                outcome = dict(status='error', error=type(exc).__name__, reason=str(exc))
            environment_after = self.session.adapter.snapshot()
            receipt = dict(event_id=event, context=context, action=self.action,
                           outcome=deepcopy(outcome),
                           model_calls=self.session.calls-before,
                           cost_unit='worker_invocations_not_energy',
                           environment=dict(before=environment_before,after=environment_after,
                               route_attempts=environment_after['attempts']-environment_before['attempts'],
                               route_failures=environment_after['failures']-environment_before['failures'],
                               preference_switches=environment_after['switches']-environment_before['switches']))
            # Neither a valid quotation nor a technical error is a semantic label.
            try:
                verdict = self.evaluate(deepcopy(request), deepcopy(outcome))
                if verdict is None:
                    return dict(receipt, feedback='unverified')
                if type(verdict) is not dict or set(verdict) != {
                        'success', 'quality', 'interventions', 'evidence_id'}:
                    raise ValueError('Exact host evaluation required')
                if type(verdict['success']) is not bool:
                    raise ValueError('Boolean verified success required')
                if not 0 <= finite(verdict['quality'], 'quality') <= 1:
                    raise ValueError('Quality outside [0,1]')
                if type(verdict['interventions']) is not int or not 0 <= verdict['interventions'] <= 1000000:
                    raise ValueError('Invalid intervention count')
                label(verdict['evidence_id'])
            except Exception as exc:
                return dict(receipt, feedback='unverified', evaluation_error=type(exc).__name__)
            receipt['verdict'] = deepcopy(verdict)
            fact = dict(event_id=event, context=context, action=self.action,
                        success=verdict['success'], quality=verdict['quality'],
                        interventions=verdict['interventions'], cost=receipt['model_calls'],
                        environment={key:receipt['environment'][key] for key in
                                     ('route_attempts','route_failures','preference_switches')})
            self.pending = (receipt, fact)
            try:
                return self._record()
            except Exception as exc:
                return dict(receipt, feedback='pending', storage_error=type(exc).__name__)
