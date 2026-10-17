"""Offline candidate-evidence API example; fixture callbacks, no model/network."""
import json,tempfile
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.evidence_context_session import EvidenceContextSession

def main():
    with tempfile.TemporaryDirectory(prefix='ocn-context-example-') as tmp:
        root=Path(tmp);docs=root/'docs';docs.mkdir()
        (docs/'event.md').write_text('The workshop is Friday.\n\nNo certifying institution is identified.')
        adapter=DocumentAdapter(docs,root/'pins.json');adapter.bind('event','event.md')
        def selector(request):
            return {'date':['s0:p0'],'certifier':['s0:p1']}
        def answerer(request):
            return {'date':dict(status='supported',answer='Friday',references=['s0:p0']),
                    'certifier':dict(status='unknown',answer=None,references=[])}
        session=EvidenceContextSession(adapter,answerer,lambda:'fixture-v1',selector=selector)
        fields={'date':'When is the workshop?','certifier':'Which institution certifies it?'}
        first=session.answer('Workshop information?',fields,('event',))
        (docs/'event.md').rename(docs/'moved.md')
        second=session.answer('Workshop information?',fields,('event',))
        assert second['session']['selection_cache_hit']
        assert second['session']['callback_invocations']==1
        assert second['sources']['event']['path']=='moved.md'
        assert second['fields']==first['fields']
        assert not second['semantic_verification']
        print(json.dumps(second,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
