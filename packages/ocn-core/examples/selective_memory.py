"""Selective metadata admission with bounded retirement and durable task receipts.

Offline demonstration: decisions are scripted, no LLM or physical energy claim.
"""
import json
from pathlib import Path
import tempfile
from ocn_core import (RepackingAgent,RepackingDNA,CompactReservoir,DissipativeHabitat,
                     ToolSession,TaskSpec,load_checkpoint,recover_task_receipt)
from ocn_core.controller import descriptor_digest


def action(op,path='',value=0):return dict(op=op,path=path,value=value)


with tempfile.TemporaryDirectory(prefix='ocn-selective-memory-') as tmp:
    root=Path(tmp);h=root/'habitat';h.mkdir();state=root/'state.json'
    dna=RepackingDNA(source_ids=('s',),max_cache=1,max_calls=8,require_schema_binding=True,
                     scheduler='paced32',aggregation='eager',emission_phase='after')
    agent=RepackingAgent('reactive',{'s':'old.json'},dna)
    sink=CompactReservoir(root/'reservoir.sqlite',2)
    task=TaskSpec('sum',('s',));report=[]
    good=dict(codec='integer',value_path=['amount'])
    for step in range(3):
        if step:agent=load_checkpoint(state,dna,'reactive')
        descriptor=dict(codec='binary_integer',value_path=['amount']) if step==1 else good
        value=(55,'101',81)[step]
        for name,data in {
            'directory.json':{'s':'new.json'},'schemas.json':{'s':descriptor},
            'new.json':dict(source='s',step=step,amount=value,schema_digest=descriptor_digest(descriptor))
        }.items():(h/name).write_text(json.dumps(data))
        request_id=f'{step+1:032x}'
        tools=DissipativeHabitat(h,dna,sink)
        session=ToolSession(agent,tools,step,max_decisions=10,task=task,
                            request_id=request_id,stage_metadata=True)
        if step==0:
            assert session.execute(action('locate'))['result']=='new.json'
            assert session.execute(action('describe'))['ok']
            assert agent.paths['s']=='old.json' # Still an unvalidated candidate.
        feedback=session.execute(action('read','new.json'))
        if step==1:
            assert feedback['error']=='schema'
            assert session.execute(action('describe'))['error']=='unsupported'
            assert agent.descriptors['s']==good # Unsupported candidate not promoted.
            assert session.execute(action('abstain'))['ok']
        else:
            assert feedback['result']==value
            calculated=session.execute(action('evaluate'))
            assert calculated['result']==value
            assert session.execute(action('finish',value=value))['ok']
        result=session.persist(state)
        receipt=recover_task_receipt(state,dna,'reactive',request_id=request_id,step=step,task=task)
        assert receipt['outcome']['answer']==result['answer']
        report.append(dict(step=step,answer=result['answer'],refused=result['refused'],
                           cost=result['cost'],retired_events=agent.retirement['retired_events']))
    assert [r['answer'] for r in report]==[55,None,81]
    assert [r['retired_events'] for r in report]==[2,2,2]
    print(json.dumps(dict(mode='scripted_offline',tasks=report,
                         note='Two retired transitions remain pending; no physical energy measured.')))
