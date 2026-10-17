"""Compact structural observations; never disclose source text or test oracles."""
from .candidate_evaluation import canonical
from .document_adapter import DocumentAdapter
from .sandbox_trial import run_trial


def summarize(documents,result):
    violations=[]
    summary=dict(document_count=len(documents),empty_document_count=sum(d['text']=='' for d in documents))
    if result['status']!='completed':
        return dict(summary,violations=['isolated_execution_failed'])
    value=result['result']
    if type(value) is not dict or set(value)!={'response','usage'} or type(value.get('usage')) is not dict:
        return dict(summary,violations=['invalid_response_envelope'])
    response=value['response']
    if (type(response) is not dict or set(response)!={'answer','abstain','citations'}
        or type(response['answer']) is not str or type(response['abstain']) is not bool
        or type(response['citations']) is not list):
        return dict(summary,violations=['invalid_response_schema'])
    if not response['answer'].strip():violations.append('empty_answer')
    citations=response['citations']
    if len(citations)>8:violations.append('too_many_citations')
    if response['abstain'] != (not citations):violations.append('citation_abstention_mismatch')
    known={d['document_id']:d['text'] for d in documents}
    for citation in citations:
        if (type(citation) is not dict or set(citation)!={'document_id','quote'}
            or type(citation['document_id']) is not str or type(citation['quote']) is not str):
            violations.append('invalid_citation_schema');continue
        if not citation['quote'].strip():violations.append('empty_citation')
        elif citation['document_id'] not in known or citation['quote'] not in known[citation['document_id']]:
            violations.append('unsupported_citation')
    return dict(summary,violations=sorted(set(violations)))


def observe(root,config,integration):
    adapter=DocumentAdapter(config['habitat'],root/'documents.json')
    snapshots=[adapter.read(i) for i in config['documents']]
    documents=[dict(document_id=d.document_id,text=d.text,sha256=d.sha256) for d in snapshots]
    if len(canonical(dict(question=config['mission'],documents=documents)))>16384:
        raise ValueError('Observation context budget exceeded')
    result=run_trial(integration,model=config['model'],question=config['mission'],documents=documents)
    if any(adapter.read(d.document_id).sha256!=d.sha256 for d in snapshots):
        raise ValueError('Source changed during observation')
    return dict(format='gat.structural-observation.v1',source_sha256=integration.descriptor()['sha256'],
                **summarize(documents,result))
