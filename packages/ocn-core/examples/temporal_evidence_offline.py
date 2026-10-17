"""Moved source and temporal selection; fixture interpretations, no LLM."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.temporal_evidence import Statement,from_source,select_at


def main():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);docs=root/'docs';docs.mkdir()
        (docs/'old.md').write_text('The shoes are in the drawer.')
        (docs/'new.md').write_text('The shoes are now in the locker.')
        adapter=DocumentAdapter(docs,root/'sources.json')
        adapter.bind('old','old.md');adapter.bind('new','new.md')
        (docs/'new.md').rename(docs/'relocated.md')
        records=[]
        for source,value,observed,effective in (
            ('old','drawer','2026-10-01T12:00:00+00:00','2026-10-01T12:00:00+00:00'),
            ('new','locker','2026-10-03T12:00:00+00:00','2026-10-02T12:00:00+00:00')):
            document=adapter.read(source)
            record=from_source(document.text,subject='shoes',predicate='location',value=value,
                observed_at=observed,effective_at=effective,source_id=source,quote=document.text)
            assert record.source_sha256==document.sha256
            records.append(record)
        memory=root/'statements.json'
        memory.write_text(json.dumps([asdict(r) for r in records]))
        reopened=[Statement(**r) for r in json.loads(memory.read_text())]
        def query(known,effective):
            return select_at(reopened,subject='shoes',predicate='location',
                known_at=known,effective_at=effective)
        current=query('2026-10-03T12:00:00+00:00','2026-10-03T12:00:00+00:00')
        historical=query('2026-10-03T12:00:00+00:00','2026-10-01T12:00:00+00:00')
        earlier_knowledge=query('2026-10-02T12:00:00+00:00','2026-10-02T12:00:00+00:00')
        assert current['value']=='locker'
        assert historical['value']==earlier_knowledge['value']=='drawer'
        assert adapter.read('new').path=='relocated.md'
        print(json.dumps(dict(status='passed',current=current['value'],historical=historical['value'],
            before_late_observation=earlier_knowledge['value'],relocation_verified=True,
            statements_preserved=len(reopened),model_calls=0,
            scope='fixture dates and host-assigned semantic mapping; not autonomous extraction')))

if __name__=='__main__':main()
