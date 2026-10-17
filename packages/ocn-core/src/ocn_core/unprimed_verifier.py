"""Optional, candidate-free semantic assessment of bounded JSON records.

The reviewer is a trusted host callback, not a truth oracle. References establish
where a value occurs, not whether the reviewer's semantic judgment is correct.
Budgets count callback invocations, not hidden model calls or energy. No cache,
persistence, networking, automatic activation or execution authority is provided.
DocumentSkillSession must still enforce file freshness and host permissions.
"""
from copy import deepcopy
import hashlib
import json
import math
from threading import Lock


def _snapshot(record):
    nodes = [0]
    def check(value, depth):
        nodes[0] += 1
        if nodes[0] > 256 or depth > 16:
            raise ValueError('Record structure exceeds bounds')
        kind = type(value)
        if kind is dict:
            if any(type(k) is not str or not k or len(k) > 128 for k in value):
                raise ValueError('Bounded string keys required')
            for child in value.values(): check(child, depth + 1)
        elif kind is list:
            for child in value: check(child, depth + 1)
        elif kind is int:
            if value.bit_length() > 256: raise ValueError('Integer exceeds bounds')
        elif kind is float:
            if not math.isfinite(value): raise ValueError('Finite JSON numbers required')
        elif kind not in (str, bool, type(None)):
            raise ValueError('Plain JSON values required')
    if type(record) is not dict: raise ValueError('JSON object record required')
    check(record, 0)
    raw = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > 16384: raise ValueError('Record byte budget exceeded')
    return json.loads(raw), raw


def evidence_catalog(record):
    """Deterministic leaf references disjoint from every textual leaf value."""
    snapshot, _ = _snapshot(record)
    leaves = []
    def walk(value, path):
        if type(value) is dict:
            for key in sorted(value): walk(value[key], path + [key])
        elif type(value) is list:
            for index, child in enumerate(value): walk(child, path + [index])
        else:
            if len(leaves) >= 64: raise ValueError('Reference count exceeds bounds')
            leaves.append(dict(path=path, value=value))
    walk(snapshot, [])
    reserved = {leaf['value'] for leaf in leaves if type(leaf['value']) is str}
    index = 0
    for leaf in leaves:
        while 'e' + str(index) in reserved: index += 1
        leaf['id'] = 'e' + str(index)
        index += 1
    return leaves


def _text(value, maximum, label):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError('Bounded nonempty ' + label + ' required')
    return value


class UnprimedVerifier:
    def __init__(self, question, reviewer, *, reviewer_id, max_calls=64,
                 allow_exact_value_aliases=True):
        self.question = _text(question, 4096, 'question')
        self.reviewer_id = _text(reviewer_id, 128, 'reviewer identity')
        if not callable(reviewer): raise ValueError('Reviewer callback required')
        if type(max_calls) is not int or not 1 <= max_calls <= 10000:
            raise ValueError('Bounded callback budget required')
        if type(allow_exact_value_aliases) is not bool:
            raise ValueError('Explicit alias flag required')
        self.reviewer = reviewer
        self.max_calls = max_calls
        self.allow_exact_value_aliases = allow_exact_value_aliases
        self.calls = 0
        self._lock = Lock()

    def assess(self, record, document_id):
        """Return a version-bound conclusion without accepting any candidate."""
        if not self._lock.acquire(blocking=False): raise RuntimeError('Verifier busy')
        try:
            identity = _text(document_id, 128, 'document identity')
            snapshot, raw = _snapshot(record)
            refs = evidence_catalog(snapshot)
            request = dict(question=self.question, document_id=identity,
                           record=snapshot, evidence_catalog=refs)
            if self.calls >= self.max_calls: raise RuntimeError('Reviewer budget exhausted')
            self.calls += 1  # Charge before invocation, including malformed responses.
            answer = self.reviewer(deepcopy(request))
            if type(answer) is not dict or set(answer) != {'status', 'reference', 'reason'}:
                raise ValueError('Conclusion schema invalid')
            status = answer['status']
            if type(status) is not str or status not in ('value', 'absent', 'ambiguous'):
                raise ValueError('Conclusion status invalid')
            reason = _text(answer['reason'], 2048, 'conclusion reason')
            selected = None
            if status != 'value':
                if answer['reference'] is not None:
                    raise ValueError('Non-value conclusion must have null reference')
            else:
                token = _text(answer['reference'], 16384, 'reference')
                matches = [r for r in refs if r['id'] == token or
                           (self.allow_exact_value_aliases and type(r['value']) is str and r['value'] == token)]
                if len(matches) != 1: raise ValueError('Unambiguous reference required')
                selected = matches[0]
                _text(selected['value'], 16384, 'resolved text value')
            record_hash = hashlib.sha256(raw).hexdigest()
            contract = dict(question=self.question, document_id=identity,
                            record_sha256=record_hash, reviewer_id=self.reviewer_id,
                            allow_exact_value_aliases=self.allow_exact_value_aliases)
            return dict(status=status, value=selected['value'] if selected else None,
                        reference=deepcopy(selected), reason=reason,
                        record_sha256=record_hash, document_id=identity,
                        contract_sha256=hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                        reviewer_id=self.reviewer_id, reviewer_calls=self.calls,
                        action_authorized=False)
        finally:
            self._lock.release()

    def compare(self, record, document_id, candidate):
        """Only compare locally, after the reviewer has formed its conclusion."""
        candidate = _text(candidate, 16384, 'candidate text')
        receipt = self.assess(record, document_id)
        return dict(receipt, candidate_accepted=receipt['status'] == 'value' and receipt['value'] == candidate)

    def verify(self, record, document_id, candidate):
        return self.compare(record, document_id, candidate)['candidate_accepted']
