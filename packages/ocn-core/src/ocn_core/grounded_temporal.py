"""Ground dates lexically and retain extraction polarity; semantics remain unverified.

Only explicit ISO calendar dates are supported, interpreted as midnight UTC.
This does not prove that a quoted date modifies the requested relationship, nor
that the extractor identified its entity, polarity or all relevant statements.
"""
from dataclasses import asdict
from datetime import date
import re
from .experience_memory import label
from .temporal_evidence import from_source,instant,select_at

POLARITIES=('affirmed','negated','hypothetical','uncertain')


def extraction_schema(source_ids):
    if type(source_ids) not in (tuple,list) or not 1<=len(source_ids)<=16:raise ValueError('Bounded source IDs required')
    for ident in source_ids:label(ident)
    if len(set(source_ids))!=len(source_ids):raise ValueError('Duplicate source ID')
    item=dict(type='object',additionalProperties=False,
        required=['source_id','value','quote','polarity','date_quote'],properties=dict(
            source_id=dict(type='string',enum=list(source_ids)),
            value=dict(type='string',description='Literal location noun phrase copied from the quote, without negation or prepositions.'),
            quote=dict(type='string',description='Exact source excerpt including the date if one applies.'),
            polarity=dict(type='string',enum=list(POLARITIES)),
            date_quote=dict(type=['string','null'],description='Exact YYYY-MM-DD within quote that dates this statement; null if unknown. Never use observation metadata.')))
    return dict(type='object',additionalProperties=False,required=['statements'],
                properties=dict(statements=dict(type='array',maxItems=64,items=item)))


def assess_extraction(extraction,sources,*,subject,predicate,known_at,effective_at):
    label(subject);label(predicate);known=instant(known_at);cutoff=instant(effective_at)
    if type(sources) is not dict:raise ValueError('Source catalogue required')
    extraction_schema(list(sources))
    total=0
    for source in sources.values():
        if type(source) is not dict or set(source)!={'text','observed_at'} or type(source['text']) is not str:
            raise ValueError('Text and host observation time required')
        total+=len(source['text'].encode());instant(source['observed_at'])
    if total>1024*1024:raise ValueError('Source budget exceeded')
    if (type(extraction) is not dict or set(extraction)!={'statements'} or
        type(extraction['statements']) is not list or len(extraction['statements'])>64):
        raise ValueError('Bounded extraction object required')
    groups={p:[] for p in POLARITIES};audit=[]
    for item in extraction['statements']:
        if type(item) is not dict or set(item)!={'source_id','value','quote','polarity','date_quote'}:
            raise ValueError('Invalid statement fields')
        ident=item['source_id'];polarity=item['polarity'];literal=item['date_quote']
        if type(ident) is not str or ident not in sources or type(polarity) is not str or polarity not in groups:
            raise ValueError('Unknown source or polarity')
        if type(item['quote']) is not str:raise ValueError('Literal quote required')
        effective=None
        if literal is not None:
            if type(literal) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}',literal) is None or literal not in item['quote']:
                raise ValueError('Effective date must be quoted explicitly')
            effective=date.fromisoformat(literal).isoformat()+'T00:00:00+00:00'
        source=sources[ident]
        statement=from_source(source['text'],subject=subject,predicate=predicate,value=item['value'],
            observed_at=source['observed_at'],effective_at=effective,source_id=ident,quote=item['quote'])
        audit.append(dict(**asdict(statement),polarity=polarity,date_quote=literal))
        if instant(statement.observed_at)>known:continue
        if effective is not None and instant(effective)>cutoff:continue
        groups[polarity].append(statement)
    result=select_at(groups['affirmed'],subject=subject,predicate=predicate,known_at=known_at,effective_at=effective_at)
    if groups['uncertain']:
        result.update(status='unresolved_polarity',value=None)
    elif result['status']=='selected_statement':
        latest=max(instant(s.effective_at) for s in groups['affirmed'] if s.effective_at is not None)
        contradicting=[s for s in groups['negated'] if s.value==result['value'] and
            (s.effective_at is None or instant(s.effective_at)>=latest)]
        if contradicting:
            result.update(status='negated_without_replacement',value=None,
                          negative_evidence=[asdict(s) for s in contradicting])
    result.update(extraction_audit=audit,classification_source='unverified_extractor',
                  date_convention='explicit_iso_calendar_date_midnight_utc')
    return result
