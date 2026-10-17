"""One bounded local-model document request; uses only an installed model.

Enrollment and cache are temporary for this CLI. Use the Python API for a
long-lived session. Documents are read but never modified by this example.
"""
import argparse,json,sys,tempfile
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.evidence_context_session import EvidenceContextSession
from ocn_core.local_evidence_context import LocalEvidenceContextWorker
from ocn_core.lexical_context import LexicalContextSelector

def pairs(values,label):
    result={}
    for value in values:
        key,sep,text=value.partition('=')
        if not sep or not key.strip() or not text.strip() or key in result:
            raise ValueError('Use distinct '+label+'=value entries')
        result[key]=text
    if not 1<=len(result)<=8:raise ValueError('One to eight '+label+' entries required')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',required=True,help='Exact already-installed Ollama model name')
    p.add_argument('--habitat',required=True,type=Path)
    p.add_argument('--document',action='append',required=True,help='ID=relative/path.md')
    p.add_argument('--field',action='append',required=True,help='name=question for this field')
    p.add_argument('--question',required=True)
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--full-context',action='store_true',help='Skip selection; one inference instead of two')
    modes.add_argument('--lexical-context',choices=('bm25','coverage','unique-coverage'),help='Local lexical selection; one model inference, incomplete coverage remains possible')
    args=p.parse_args();worker=None
    try:
        documents=pairs(args.document,'document');fields=pairs(args.field,'field')
        with tempfile.TemporaryDirectory(prefix='ocn-local-context-') as tmp:
            adapter=DocumentAdapter(args.habitat,Path(tmp)/'pins.json')
            for ident,path in documents.items():adapter.bind(ident,path)
            limit=1 if args.full_context or args.lexical_context else 2
            worker=LocalEvidenceContextWorker(args.model,max_calls=limit)
            selector=None if args.full_context else worker.select
            revision=worker.revision
            if args.lexical_context:
                selector=LexicalContextSelector(entity_coverage=args.lexical_context!='bm25',
                    deduplicate=args.lexical_context=='unique-coverage')
                revision=lambda:worker.revision()+':'+selector.revision()
            session=EvidenceContextSession(adapter,worker.answer,revision,
                selector=selector,max_callbacks=1 if args.full_context else 2)
            result=session.answer(args.question,fields,tuple(documents))
            print(json.dumps(dict(receipt=result,model_attempts=worker.attempts()),ensure_ascii=False,indent=2))
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps(dict(error=type(exc).__name__+': '+str(exc),model_attempts=worker.attempts() if worker else []),ensure_ascii=False),file=sys.stderr)
        return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
