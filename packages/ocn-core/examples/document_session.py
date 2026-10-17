"""Bounded JSON-lines document session with one already-installed local model.

Each input is {"id": "q1", "question": "...", "fields": {"field": "description"}}.
The host enrolls documents at startup; input cannot grant tools or update versions.
EOF closes the session. Neither bindings nor selection memory survive restart.
"""
import argparse,json,sys,tempfile
from contextlib import ExitStack
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.live_document_adapter import LiveDocumentAdapter
from ocn_core.evidence_context_session import EvidenceContextSession
from ocn_core.adaptive_context_session import AdaptiveContextSession
from ocn_core.lexical_context import LexicalContextSelector
from ocn_core.local_evidence_context import LocalEvidenceContextWorker

def documents(values):
    result={}
    for value in values:
        key,sep,path=value.partition('=')
        if not sep or not key.strip() or not path.strip() or key in result:
            raise ValueError('Distinct ID=relative/path.md documents required')
        result[key]=path
    if not 1<=len(result)<=8:raise ValueError('One to eight documents required')
    return result

def unique_object(pairs):
    result=dict(pairs)
    if len(result)!=len(pairs):raise ValueError('Duplicate JSON keys')
    return result

def reject_constant(value):
    raise ValueError('Nonfinite JSON value')

def serve(args,stdin,stdout):
    """Synchronous host protocol, bounded input/requests/model calls, no daemon."""
    def emit(value):stdout.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n');stdout.flush()
    worker=None
    try:
        if type(args.max_requests) is not int or not 1<=args.max_requests<=128:
            raise ValueError('Request limit must be 1..128')
        if type(args.max_model_calls) is not int or not 1<=args.max_model_calls<=64:
            raise ValueError('Model call limit must be 1..64')
        if args.selection not in ('full','bm25','coverage','unique-coverage','llm','source-windows'):
            raise ValueError('Unknown selection strategy')
        max_passages=getattr(args,'max_passages',256)
        if type(max_passages) is not int or not 1<=max_passages<=2048:
            raise ValueError('Passage limit must be 1..2048')
        if args.selection=='source-windows' and args.max_requests>64:
            raise ValueError('Adaptive request limit must be 1..64')
        enrolled=documents(args.document)
        with tempfile.TemporaryDirectory(prefix='ocn-document-session-') as tmp,ExitStack() as lifetime:
            adapter=(LiveDocumentAdapter if args.live_identity else DocumentAdapter)(args.habitat,Path(tmp)/'bindings.json')
            if args.live_identity:lifetime.callback(adapter.close)
            for ident,path in enrolled.items():
                adapter.bind(ident,path)
                if args.live_identity:adapter.pin(ident)
            worker=LocalEvidenceContextWorker(args.model,max_calls=args.max_model_calls)
            if args.selection=='source-windows':
                session=AdaptiveContextSession(adapter,worker,selection='source-windows',
                    max_requests=args.max_requests,max_paragraphs=max_passages)
            else:
                selector=None;revision=worker.revision
                if args.selection=='llm':selector=worker.select
                elif args.selection!='full':
                    selector=LexicalContextSelector(entity_coverage=args.selection!='bm25',
                        deduplicate=args.selection=='unique-coverage')
                    revision=lambda:worker.revision()+':'+selector.revision()
                session=EvidenceContextSession(adapter,worker.answer,revision,selector=selector,
                    max_callbacks=args.max_model_calls*(2 if selector is not None else 1),max_requests=args.max_requests,max_paragraphs=max_passages)
            emit(dict(event='ready',model=args.model,model_digest=worker.model_digest,
                selection=args.selection,identity='live-process' if args.live_identity else 'exact-version',
                max_requests=args.max_requests,max_model_calls=args.max_model_calls,
                persistence='none',action_authorized=False,max_passages=max_passages))
            ids=set();received=0;succeeded=0;reason='request_limit'
            for _ in range(args.max_requests):
                line=stdin.readline(32769)
                if not line:reason='eof';break
                received+=1;ident=None;before=worker.calls;session_started=False
                if len(line)>32768 or len(line.encode())>32768:
                    emit(dict(event='error',id=None,error='Input line exceeds 32768 bytes'))
                    reason='input_limit';break
                try:
                    request=json.loads(line,object_pairs_hook=unique_object,parse_constant=reject_constant)
                    if type(request) is not dict or set(request)!={'id','question','fields'}:
                        raise ValueError('Exact id/question/fields input required')
                    candidate_id=request['id']
                    if type(candidate_id) is not str or not candidate_id.strip() or len(candidate_id.encode())>128:
                        raise ValueError('Bounded nonempty request id required')
                    ident=candidate_id
                    if ident in ids:raise ValueError('Request id already used')
                    ids.add(ident)
                    session_started=True
                    receipt=session.answer(request['question'],request['fields'],tuple(enrolled))
                except (ValueError,RuntimeError,OSError,RecursionError) as exc:
                    event=dict(event='error',id=ident,error=type(exc).__name__+': '+str(exc),
                        new_model_calls=worker.calls-before,model_calls=worker.calls,
                        attempts=worker.attempts()[before:])
                    if args.selection=='source-windows':
                        event['context_routing']=session.last_attempt() if session_started else None
                    emit(event)
                else:
                    succeeded+=1
                    emit(dict(event='answer',id=ident,receipt=receipt,new_model_calls=worker.calls-before,
                        model_calls=worker.calls,attempts=worker.attempts()[before:]))
                if worker.calls>=args.max_model_calls:reason='model_call_limit';break
            emit(dict(event='closed',reason=reason,received=received,succeeded=succeeded,
                model_calls=worker.calls,action_authorized=False))
        return 0
    except (ValueError,RuntimeError,OSError) as exc:
        emit(dict(event='fatal',error=type(exc).__name__+': '+str(exc),
            model_calls=worker.calls if worker else 0))
        return 1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',required=True)
    parser.add_argument('--habitat',type=Path,required=True)
    parser.add_argument('--document',action='append',required=True)
    parser.add_argument('--selection',choices=('full','bm25','coverage','unique-coverage','llm','source-windows'),default='full')
    parser.add_argument('--live-identity',action='store_true')
    parser.add_argument('--max-passages',type=int,default=256,help='Maximum source passages, including sentence expansion for source-windows (1..2048)')
    parser.add_argument('--max-requests',type=int,default=8)
    parser.add_argument('--max-model-calls',type=int,default=16)
    return serve(parser.parse_args(),sys.stdin,sys.stdout)
if __name__=='__main__':raise SystemExit(main())
