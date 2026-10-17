"""Real file relocation plus procedural learning and numeric synthesis; fixture worker."""
import json,tempfile
from decimal import Decimal
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_skill_session import DocumentSkillSession


def main():
    with tempfile.TemporaryDirectory(prefix='ocn-document-skills-') as tmp:
        root=Path(tmp);docs=root/'documents';docs.mkdir()
        adapter=DocumentAdapter(docs,root/'index.json')
        expected={f'D{n}':f'{n*175} g' for n in range(1,5)}
        for identity,value in expected.items():
            (docs/f'{identity}.txt').write_text(json.dumps({'id':identity,'cargo':{'net':value}}))
            adapter.bind(identity,f'{identity}.txt')
        session=DocumentSkillSession(adapter,
            lambda c,r,s,i,e:{'value':s['cargo']['net']},
            lambda c,r,s,i,o:o['value']==expected[i],
            identity_guard=lambda c,r,s,i:s.get('id')==i)
        session.permit('inventory','v1');receipts=[]
        for index,identity in enumerate(expected):
            if index==2:
                (docs/'relocated').mkdir()
                for name in ('D3','D4'):(docs/f'{name}.txt').rename(docs/'relocated'/f'{name}.txt')
            receipts.append(session.answer(identity,connector='inventory',revision='v1',identity=identity,
                allowance=12,acquisition_cost=3,application_cost=1,delegation_cost=8))
        # Revalidate every cited version at final synthesis, including earlier reads.
        for receipt in receipts:
            assert adapter.read(receipt['source']['document_id']).sha256==receipt['source']['sha256']
        total=sum(Decimal(r['output']['value'].split()[0]) for r in receipts)
        assert total==1750 and session.skills.worker_calls==2
        print(json.dumps(dict(status='passed',total=f'{total} g',
            rows=[dict(value=r['output']['value'],action=r['action'],source=r['source']) for r in receipts],
            worker_calls=session.skills.worker_calls,new_llm_calls=0,
            scope='Four structured documents, real temporary file moves, fixture worker and host labels; not general prose synthesis.'),indent=2))

if __name__=='__main__':main()
