"""Actual file relocation and invalidation of a persisted extraction, no model."""
import json
from pathlib import Path
import tempfile
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.temporal_document_memory import query
from ocn_core.temporal_extraction_session import extract_and_capture


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);docs=root/'docs';docs.mkdir()
        first='On 2026-01-01, the shoes are in the drawer.'
        second='On 2026-01-02, the shoes are in the locker.'
        adapter=DocumentAdapter(docs,root/'bindings.json');statements=[];observed={}
        for ident,text,value,date in [('old',first,'drawer','2026-01-01'),('new',second,'locker','2026-01-02')]:
            (docs/(ident+'.md')).write_text(text);adapter.bind(ident,ident+'.md')
            observed[ident]=date+'T00:00:00+00:00'
            statements.append(dict(source_id=ident,value=value,quote=text,polarity='affirmed',date_quote=date))
        state=root/'memory.json'
        calls=[]
        def extractor(request):
            calls.append(request)
            assert {d['text'] for d in request['documents']}=={first,second}
            return dict(extraction=dict(statements=statements),usage=dict(model_calls=0))
        receipt=extract_and_capture(adapter,state,extractor,observed,subject='shoes',predicate='location')
        (docs/'new.md').rename(docs/'moved.md')
        adapter=DocumentAdapter(docs,root/'bindings.json')
        kwargs=dict(expected_sha256=receipt['memory_sha256'],known_at=observed['new'])
        current=query(adapter,state,effective_at=observed['new'],**kwargs)
        historical=query(adapter,state,effective_at=observed['old'],**kwargs)
        assert current['candidate_value']=='locker' and historical['candidate_value']=='drawer'
        assert any(p['relocated_from']=='new.md' for p in current['provenance'])
        (docs/'moved.md').write_text('Different version, not authorized.')
        invalidated=query(adapter,state,effective_at=observed['new'],**kwargs)
        assert invalidated['status']=='unresolved_provenance' and invalidated['candidate_value'] is None
        assert len(calls)==1
        print(json.dumps(dict(status='passed',current_candidate=current['candidate_value'],
            historical_candidate=historical['candidate_value'],after_change=invalidated['status'],
            extractor_invocations=len(calls),model_calls=0,semantic_verification=False,scope='host-authored extraction; real files, no autonomous semantic verification')))

if __name__=='__main__':main()
