"""Bounded procedural session for verified scalar extraction.

Uses the existing structural learner; does not generate arbitrary skills.
Admission uses host-declared cost bounds, not measured joules or deadline guarantees.
The trusted evaluator must check semantics; neither citations nor admission prove it.
Single owner, in-process only. No automatic service activation or quaternion claim.
Opt-in feedback learning accepts at most two diverse bounded observations per
host-permitted connector/revision. Only worker results with an explicit positive
host verdict are admitted. This reduces manual example preparation, not the need
for a trustworthy semantic evaluator. It does not validate arbitrary schemas.
The host selects skill_kind='mass' or 'text'; keep one field objective per session.
"""
from copy import deepcopy
import math
import hashlib
from .skill_bank import SkillBank
from .mass_read_skill import encoded, shape, _validate_examples


def amount(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Finite nonnegative declared cost required')
    return value


class SkillSession:
    def __init__(self, worker, evaluate, *, capacity=2, max_requests=64, max_worker_calls=32,
                 learn_from_feedback=False, adapt_schema_changes=False, identity_guard=None,
                 delegate_unsupported_shapes=False, skill_kind='mass', retry_rejected_skill=False):
        if not callable(worker) or not callable(evaluate):
            raise ValueError('Worker and trusted semantic evaluator required')
        for limit in (max_requests, max_worker_calls):
            if type(limit) is not int or not 1 <= limit <= 10000:
                raise ValueError('Bounded positive integer limits required')
        if type(retry_rejected_skill) is not bool:
            raise ValueError('Explicit retry flag required')
        if retry_rejected_skill and not learn_from_feedback:
            raise ValueError('Recovery requires feedback learning')
        self.retry_rejected_skill = retry_rejected_skill
        self.bank = SkillBank(capacity,kind=skill_kind)
        self.worker, self.evaluate = worker, evaluate
        self.max_requests, self.max_worker_calls = max_requests, max_worker_calls
        self.requests = self.worker_calls = 0
        if type(learn_from_feedback) is not bool:
            raise ValueError('Explicit feedback learning flag required')
        self.learn_from_feedback = learn_from_feedback
        self.permissions = {}
        self.examples = {}
        if type(adapt_schema_changes) is not bool:
            raise ValueError('Explicit schema adaptation flag required')
        if adapt_schema_changes and (not learn_from_feedback or not callable(identity_guard)):
            raise ValueError('Schema adaptation requires feedback learning and an identity guard')
        self.adapt_schema_changes = adapt_schema_changes
        self.identity_guard = identity_guard
        if type(delegate_unsupported_shapes) is not bool or (delegate_unsupported_shapes and not adapt_schema_changes):
            raise ValueError('Unsupported-shape delegation requires guarded schema adaptation')
        self.delegate_unsupported_shapes = delegate_unsupported_shapes
        self.schema_events = []
        self.learned_calibrations = set()
        self.retirement_events = []

    def _retire_learned(self, connector, reason):
        if connector not in self.learned_calibrations:
            return False
        authority = self.bank.authority[connector]
        self.retirement_events.append(dict(connector=connector,revision=authority['revision'],
            calibration_sha256=authority['digest'],reason=reason,request=self.requests))
        self.retirement_events = self.retirement_events[-16:]
        self.bank.entries.pop(connector, None)
        self.bank.authority.pop(connector, None)
        self.examples.pop(connector, None)
        self.learned_calibrations.discard(connector)
        return True

    def _check_schema(self, connector, revision, record, identity, authority):
        if self.identity_guard(connector,revision,deepcopy(record),identity) is not True:
            raise ValueError('Host envelope identity rejected')
        if self.delegate_unsupported_shapes:
            encoded(record)  # Enforce byte/JSON bounds even when the learner cannot model it.
        try:
            observed_shape=shape(record)
        except ValueError:
            if not self.delegate_unsupported_shapes:raise
            return authority, False
        current = hashlib.sha256(encoded(observed_shape)).hexdigest()
        samples = authority['examples'] if authority else self.examples.get(connector, [])
        if samples:
            previous = hashlib.sha256(encoded(shape(samples[0]['record']))).hexdigest()
            if previous != current:
                if authority is not None and connector not in self.learned_calibrations:
                    raise ValueError('Host calibration schema changed; host revision required')
                # Retire stale method and its training examples, never change permission.
                self._retire_learned(connector, 'observed_schema_change')
                self.bank.entries.pop(connector, None)
                self.bank.authority.pop(connector, None)
                self.examples.pop(connector, None)
                self.schema_events.append(dict(connector=connector, revision=revision,
                                               before=previous, after=current, request=self.requests))
                self.schema_events = self.schema_events[-16:]
                return None, True
        return authority, True

    def permit(self, connector, revision):
        """Host permission only. Worker feedback cannot invoke this operation.

        Two diverse, verified worker outcomes can subsequently form calibration.
        Repeating the same permission does not erase memory; revision changes do.
        """
        if not self.learn_from_feedback:
            raise ValueError('Feedback learning is not enabled')
        if any(type(v) is not str or not v.strip() or len(v)>128 for v in (connector,revision)):
            raise ValueError('Explicit connector and revision required')
        if connector not in self.permissions and len(self.permissions)>=8:
            raise ValueError('Host connector bound exceeded')
        if self.permissions.get(connector) != revision:
            self.bank.entries.pop(connector, None)
            self.bank.authority.pop(connector, None)
            self.examples.pop(connector, None)
            self.learned_calibrations.discard(connector)
        self.permissions[connector] = revision

    def authorize(self, connector, revision, examples):
        if connector not in self.permissions and len(self.permissions)>=8:
            raise ValueError('Host connector bound exceeded')
        self.bank.authorize(connector, revision, examples)
        self.permissions[connector] = revision
        self.examples.pop(connector, None)
        self.learned_calibrations.discard(connector)

    def _observe(self, connector, revision, record, identity, output):
        # Successful skill applications never supply their own training labels.
        if connector in self.bank.authority:
            return 'calibration_present'
        try:
            sample = dict(record=deepcopy(record), identity=identity, expected=output['value'])
            shape(record); encoded(sample)
            if type(identity) is not str or not 1<=len(identity)<=128:
                raise ValueError('Invalid identity')
            if type(sample['expected']) is not str or not 1<=len(sample['expected'])<=160:
                raise ValueError('Invalid value')
            previous = self.examples.get(connector, [])
            if any(s['identity']==identity or s['expected']==sample['expected'] for s in previous):
                return 'insufficient_diversity'
            candidates = previous + [sample]
            if len(candidates)==2:
                _validate_examples(candidates)
                self.bank.authorize(connector, revision, candidates)
                self.learned_calibrations.add(connector)
                self.examples.pop(connector, None)
                return 'calibration_ready'
            self.examples[connector] = candidates
            return 'observation_retained'
        except (ValueError, KeyError, TypeError, RecursionError):
            return 'unsupported_observation'

    def run(self, connector, revision, record, identity, *, allowance,
            acquisition_cost, application_cost, delegation_cost):
        costs = list(map(amount, (allowance, acquisition_cost, application_cost, delegation_cost)))
        allowance, acquisition_cost, application_cost, delegation_cost = costs
        if self.learn_from_feedback and self.permissions.get(connector)==revision:
            authority = self.bank.authority.get(connector)
        else:
            authority = self.bank.authorized(connector, revision)
        if self.requests >= self.max_requests:
            raise RuntimeError('Request budget exhausted')
        self.requests += 1
        record = deepcopy(record)
        supported=True
        if self.adapt_schema_changes:
            authority,supported = self._check_schema(connector,revision,record,identity,authority)
        known = self.bank.entries.get(connector) if supported else None
        can_delegate = self.worker_calls < self.max_worker_calls
        # Reserve both the acquisition and the more expensive possible continuation.
        acquire = (supported and authority is not None and known is None and can_delegate and
                   acquisition_cost + max(application_cost, delegation_cost) <= allowance)
        if known is not None and known[0] is not None and application_cost > allowance:
            raise RuntimeError('Application exceeds declared allowance')
        if known is None and not acquire and (not can_delegate or delegation_cost > allowance):
            raise RuntimeError('No admissible execution path')
        result = (self.bank.read(connector, revision, record, identity, acquire=acquire)
                  if supported and authority is not None else dict(status='not_acquired'))
        declared_cost = acquisition_cost if acquire else 0
        if result['status'] == 'value':
            action = 'acquire_apply' if acquire else 'apply'
            output = result['output']
            declared_cost += application_cost
        else:
            if not can_delegate or declared_cost + delegation_cost > allowance:
                raise RuntimeError('Delegation budget exhausted')
            self.worker_calls += 1  # Charge before invocation, including failures.
            output = self.worker(connector, revision, deepcopy(record), identity,
                                 deepcopy(authority['examples']) if authority else [])
            action = 'acquire_delegate' if acquire else 'delegate'
            declared_cost += delegation_cost
        verdict = self.evaluate(connector, revision, deepcopy(record), identity, deepcopy(output))
        if type(verdict) is not bool:
            raise ValueError('Explicit boolean semantic verdict required')
        recovered = False
        if not verdict:
            retired = False
            if result['status'] == 'value':
                # Never train on the rejected candidate or mutate host calibration.
                retired = self._retire_learned(connector, 'host_semantic_verdict')
                if not retired:
                    self.bank.entries[connector] = (None, {'rejected': 'host_semantic_verdict'})
            if not (self.retry_rejected_skill and retired and
                    self.worker_calls < self.max_worker_calls and
                    declared_cost + delegation_cost <= allowance):
                raise ValueError('Output failed host semantic evaluation')
            self.worker_calls += 1  # Recovery consumes the same cumulative quota.
            declared_cost += delegation_cost
            output = self.worker(connector, revision, deepcopy(record), identity, [])
            verdict = self.evaluate(connector, revision, deepcopy(record), identity, deepcopy(output))
            if type(verdict) is not bool:
                raise ValueError('Explicit boolean semantic verdict required')
            if not verdict:
                raise ValueError('Recovery output failed host semantic evaluation')
            action = 'recover_delegate'
            result = {'status': 'recovered_by_worker'}
            recovered = True
        receipt = dict(output=deepcopy(output), action=action, verified=True,
                    declared_cost=declared_cost, worker_calls=self.worker_calls,
                    memory=self.bank.stats())
        if recovered:
            receipt['recovery'] = dict(reason='rejected_learned_skill', attempts=1)
        if self.learn_from_feedback:
            receipt['learning'] = ('unsupported_observation' if not supported else
                                  self._observe(connector,revision,record,identity,output)
                                   if result['status']!='value' else 'skill_not_training_label')
        if not supported:
            receipt['delegation_reason']='outside_structural_learner_grammar'
        if self.adapt_schema_changes:
            receipt['schema_events'] = deepcopy(self.schema_events)
        return receipt
