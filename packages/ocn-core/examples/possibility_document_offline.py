"""Replan between real file operations; deterministic fixture, no LLM or benchmark.

The quaternion operators are identity here: this demonstrates the boundary between
hypotheses and verified observations, not a geometrical performance advantage.
"""
import hashlib
import json
from pathlib import Path
import tempfile
from ocn_core.possibility_space import ActionModel, explore


def digest(raw):return hashlib.sha256(raw).hexdigest()


def run_case(tamper):
    with tempfile.TemporaryDirectory(prefix='gat-possibility-doc-') as tmp:
        root=Path(tmp);source=root/'schedule.md';source.write_text('Delivery is Friday.')
        expected=digest(source.read_bytes())
        archive=root/'archive';archive.mkdir();source.rename(archive/'moved.md')
        models=[ActionModel('summarize',(0,)*4,5.,1.,terminal=True,requires=('read',)),
                ActionModel('read',(0,)*4,0.,1.,requires=('located',),adds=('read',)),
                ActionModel('locate',(0,)*4,0.,1.,adds=('located',))]
        labels=();candidate=None;snapshot=None;events=[];reserve=3.
        for step in range(3):
            proposal=explore((0,)*4,models,anchor_id='file-observation-'+str(step),
                coordinate_contract='identity-fixture-v1',authorized={'locate','read','summarize'},
                initial_conditions=labels,minimum=(-1,)*4,maximum=(1,)*4,reserve=reserve)
            assert proposal['status']=='proposed'
            action=proposal['action_id'];reserve-=1
            event=dict(action=action,proposed_path=proposal['proposal']['path'],
                       initial_conditions=list(labels),result='started')
            events.append(event)
            if action=='locate':
                matches=[p for p in sorted(root.rglob('*.md')) if digest(p.read_bytes())==expected]
                assert len(matches)==1
                candidate=matches[0];labels=('located',)
                event.update(result='observed',relative_path=str(candidate.relative_to(root)))
            elif action=='read':
                snapshot=candidate.read_bytes()
                assert digest(snapshot)==expected
                labels=('located','read')
                event.update(result='verified',sha256=expected)
                if tamper:candidate.write_text('Delivery is Monday.')
            elif action=='summarize':
                # The actual boundary checks the fresh source, not predicted labels.
                if digest(candidate.read_bytes())!=expected:
                    labels=()
                    event.update(result='refuted',reason='source_changed')
                    return dict(status='refused',answer=None,events=events,verified_conditions=list(labels))
                answer=snapshot.decode('utf-8')
                event.update(result='verified',sha256=expected)
                return dict(status='completed',answer=answer,events=events,
                            citation=dict(path=str(candidate.relative_to(root)),sha256=expected))
            else:raise AssertionError('Unknown proposed action')
        raise AssertionError('No actual terminal result')


def main():
    normal=run_case(False);changed=run_case(True)
    assert normal['answer']=='Delivery is Friday.'
    assert [e['action'] for e in normal['events']]==['locate','read','summarize']
    assert [e['proposed_path'] for e in normal['events']]==[
        ['locate','read','summarize'],['read','summarize'],['summarize']]
    assert normal['citation']['path']=='archive/moved.md'
    assert changed['status']=='refused' and changed['answer'] is None
    assert changed['verified_conditions']==[]
    print(json.dumps(dict(status='passed',normal=normal,changed_after_read=changed,
        model_calls=0,scope='file fixture and replanning boundary; no learned transitions or quaternion efficacy')))


if __name__=='__main__':main()
