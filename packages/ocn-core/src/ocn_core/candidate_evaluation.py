"""Host-defined finite acceptance suites for offline isolated bridge candidates."""
import hashlib
import json
from .agent_integration import Integration
from .sandbox_trial import run_trial


class PreExecutionAcceptanceError(RuntimeError):
    """A finite pre-execution gate failed; never a mission execution error."""
    def __init__(self,report):
        super().__init__('Current integration failed pre-execution acceptance')
        self.report=report
        self.conclusive=all(row['reason']!='sandbox_or_candidate_failure' for row in report['rows'])


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def validate_payload(value,documents):
    if type(value) is not dict or len(value)!=1:raise ValueError('One expected response or request required')
    known={d['document_id']:d['text'] for d in documents}
    if set(value)=={'request'}:
        request=value['request']
        if (type(request) is not dict or set(request)!={'operation','document_ids'}
            or request['operation']!='synthesize'):raise ValueError('Invalid expected model request')
        ids=request['document_ids']
        if (type(ids) is not list or not ids or any(type(i) is not str or i not in known for i in ids)
            or len(set(ids))!=len(ids)):raise ValueError('Invalid expected document selection')
    elif set(value)=={'response'}:
        response=value['response']
        if (type(response) is not dict or set(response)!={'answer','abstain','citations'}
            or type(response['answer']) is not str
            or type(response['abstain']) is not bool or type(response['citations']) is not list
            or len(response['citations'])>8):raise ValueError('Invalid expected response')
        if response['abstain'] != (not response['citations']):raise ValueError('Invalid expected abstention')
        if not response['abstain'] and not response['answer'].strip():raise ValueError('Expected answer must be nonempty unless abstaining')
        for citation in response['citations']:
            if (type(citation) is not dict or set(citation)!={'document_id','quote'}
                or type(citation['document_id']) is not str or citation['document_id'] not in known
                or type(citation['quote']) is not str or not citation['quote'].strip()
                or citation['quote'] not in known[citation['document_id']]):raise ValueError('Invalid expected citation')
    else:raise ValueError('Unknown expected payload')


def validate_suite(suite):
    if (type(suite) is not dict or set(suite)!={'format','cases'}
        or suite['format']!='gat.acceptance-suite.v1' or type(suite['cases']) is not list
        or not 1<=len(suite['cases'])<=16):raise ValueError('Invalid acceptance suite')
    if len(canonical(suite))>65536:raise ValueError('Acceptance suite too large')
    names=[]
    for case in suite['cases']:
        if (type(case) is not dict or set(case)!={'id','question','documents','expected'}
            or type(case['id']) is not str or not case['id'].strip() or len(case['id'])>128
            or type(case['question']) is not str or not case['question'].strip()
            or len(case['question'].encode())>4096 or type(case['documents']) is not list
            or not 1<=len(case['documents'])<=8):raise ValueError('Invalid acceptance case')
        names.append(case['id']);ids=[]
        for document in case['documents']:
            if (type(document) is not dict or set(document)!={'document_id','text'}
                or type(document['document_id']) is not str or not document['document_id'].strip()
                or len(document['document_id'])>128 or type(document['text']) is not str):
                raise ValueError('Invalid acceptance document')
            ids.append(document['document_id'])
        if len(set(ids))!=len(ids):raise ValueError('Duplicate document identifiers')
        if len(canonical(dict(question=case['question'],documents=case['documents'])))>16000:
            raise ValueError('Acceptance case context too large')
        validate_payload(case['expected'],case['documents'])
    if len(set(names))!=len(names):raise ValueError('Duplicate acceptance case identifiers')


def evaluate(integration,suite):
    if type(integration) is not Integration:raise ValueError('Prepared integration required')
    descriptor=integration.descriptor();validate_suite(suite)
    # Detach from mutable caller-owned data before the first execution.
    suite=json.loads(canonical(suite));rows=[]
    for case in suite['cases']:
        documents=[dict(d,sha256=hashlib.sha256(d['text'].encode()).hexdigest()) for d in case['documents']]
        result=run_trial(integration,model='offline-validation',question=case['question'],documents=documents)
        passed=False;reason='sandbox_or_candidate_failure';differences=['execution_failed']
        if result['status']=='completed':
            value=result['result'];expected=case['expected']
            if set(expected)=={'response'}:
                if type(value) is dict and set(value)=={'response','usage'} and type(value['usage']) is dict:
                    value={'response':value['response']}
                else:
                    value=None
            reason='unexpected_output';differences=['invalid_payload']
            try:
                validate_payload(value,case['documents'])
                passed=canonical(value)==canonical(expected)
                differences=describe_difference(value,expected)
            except (TypeError,ValueError):pass
            if passed:reason='matched_expected'
        rows.append(dict(case_id=case['id'],passed=passed,reason=reason,differences=differences))
    return dict(format='gat.acceptance-report.v1',source=descriptor,
        suite_sha256=hashlib.sha256(canonical(suite)).hexdigest(),cases=len(rows),
        passed=sum(row['passed'] for row in rows),accepted=all(row['passed'] for row in rows),
        scope='exact finite offline suite only',model_calls=0,promoted=False,rows=rows)


DIFFERENCE_CODES=frozenset(('execution_failed','invalid_payload','payload_kind_mismatch',
    'answer_mismatch','answer_surrounding_whitespace_mismatch','abstain_mismatch','citations_mismatch','request_mismatch'))


def describe_difference(actual,expected):
    """Called only after payload validation; emit facts, never source strings."""
    if set(actual)!=set(expected):return ['payload_kind_mismatch']
    if 'request' in expected:return [] if canonical(actual)==canonical(expected) else ['request_mismatch']
    a=actual['response'];e=expected['response'];codes=[]
    if a['answer']!=e['answer']:
        codes.append('answer_surrounding_whitespace_mismatch' if a['answer'].strip()==e['answer'].strip() else 'answer_mismatch')
    if a['abstain']!=e['abstain']:codes.append('abstain_mismatch')
    if canonical(a['citations'])!=canonical(e['citations']):codes.append('citations_mismatch')
    return codes


def acceptance_feedback(report):
    counts={}
    for row in report['rows']:
        for code in row['differences']:
            if code not in DIFFERENCE_CODES:raise ValueError('Unknown acceptance difference code')
            counts[code]=counts.get(code,0)+1
    return dict(format='gat.acceptance-feedback.v1',scope='operator-authorized acceptance suite, not separate controls',
        cases=report['cases'],failed=report['cases']-report['passed'],difference_counts=counts)
