"""Temporal selection of quoted statements, not semantic truth verification.

The host supplies entity/relation and effective time. Exact source/quote matching
cannot establish these interpretations. Observation time must come from the host,
never from an untrusted document timestamp. No LLM, tools or persistence here.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from .experience_memory import label


def instant(value):
    if type(value) is not str or len(value)>64:raise ValueError('Explicit zoned ISO timestamp required')
    try:parsed=datetime.fromisoformat(value[:-1]+'+00:00' if value.endswith('Z') else value)
    except ValueError as exc:raise ValueError('Invalid timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError('Timezone required')
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Statement:
    subject: str
    predicate: str
    value: str
    observed_at: str
    effective_at: str | None
    source_id: str
    source_sha256: str
    quote: str


def validate(statement):
    if type(statement) is not Statement:raise ValueError('Statement required')
    for value in (statement.subject,statement.predicate,statement.source_id):label(value)
    if type(statement.value) is not str or not statement.value or len(statement.value.encode())>4096:
        raise ValueError('Bounded literal value required')
    if type(statement.quote) is not str or not statement.quote or len(statement.quote.encode())>8192:
        raise ValueError('Bounded quote required')
    if statement.value not in statement.quote:raise ValueError('Literal value must occur in quote')
    if type(statement.source_sha256) is not str or re.fullmatch('[0-9a-f]{64}',statement.source_sha256) is None:
        raise ValueError('Source fingerprint required')
    instant(statement.observed_at)
    if statement.effective_at is not None:instant(statement.effective_at)


def from_source(text,*,subject,predicate,value,observed_at,effective_at,source_id,quote):
    """Create an anchored statement. Host semantic mapping remains unverified."""
    if type(text) is not str or len(text.encode())>1024*1024:raise ValueError('Bounded UTF-8 source required')
    statement=Statement(subject,predicate,value,observed_at,effective_at,source_id,
                        hashlib.sha256(text.encode()).hexdigest(),quote)
    validate(statement)
    if quote not in text:raise ValueError('Quote does not occur in source')
    return statement


def select_at(statements,*,subject,predicate,known_at,effective_at):
    """Select latest applicable statement among information already observed.

    No precedence from arrival order. Unknown effective times remain unresolved;
    conflicting values at the latest effective time are not settled by recency
    of arrival or list order. Previously superseded statements are not deleted.
    Caller must preserve the anchored records; direct construction is not proof.
    """
    label(subject);label(predicate);known=instant(known_at);effective=instant(effective_at)
    if type(statements) not in (list,tuple) or len(statements)>256:
        raise ValueError('At most 256 statements per query')
    visible=[];unknown=[]
    for s in statements:
        validate(s)
        if s.subject!=subject or s.predicate!=predicate or instant(s.observed_at)>known:continue
        if s.effective_at is None:unknown.append(s)
        elif instant(s.effective_at)<=effective:visible.append(s)
    result=dict(status='missing',value=None,evidence=[],semantic_verification=False,
                observation_cutoff=known.isoformat(),effective_cutoff=effective.isoformat())
    def evidence(items):
        # Return anchored records, never unquoted reconstructed claims.
        from dataclasses import asdict
        return sorted((asdict(s) for s in items),key=lambda s:(s['source_id'],s['source_sha256'],s['quote'],s['observed_at'],s['effective_at'] or '',s['value']))
    if unknown:
        result.update(status='unresolved_time',evidence=evidence(unknown+visible));return result
    if not visible:return result
    latest=max(instant(s.effective_at) for s in visible)
    selected=[s for s in visible if instant(s.effective_at)==latest]
    values={s.value for s in selected}
    result.update(status='selected_statement' if len(values)==1 else 'conflict',
                  value=next(iter(values)) if len(values)==1 else None,evidence=evidence(selected))
    return result
