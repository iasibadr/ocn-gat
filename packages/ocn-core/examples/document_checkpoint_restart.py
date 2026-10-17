"""Real process exits around document checkpoints; synthetic workers only.

The parent reopens the session after each child process terminates. No model, network or external task
is invoked. The two failpoints test unresolved intent and lost result delivery.
"""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession
from ocn_core.document_checkpoint import CheckpointedDocumentSession
from ocn_core.model_budget import PersistentAttemptBudget

REQUEST_ID='a'*32
REQUEST=dict(question='City?',fields={'city':'Copy city'},document_ids=('D',))

def session(root,mode='normal'):
    budget=PersistentAttemptBudget(root/'budget',2)
    adapter=DocumentAdapter(root/'docs',root/'pins.json')
    def worker(q,f,i,text):
        with (root/'worker_entries.jsonl').open('a') as log:
            log.write(json.dumps({'mode':mode,'reserved':budget.snapshot()['used']})+'\n')
            log.flush();os.fsync(log.fileno())
        if mode=='during_worker':os._exit(23)
        return dict(observations=[dict(source_id=i,field='city',sha256=hashlib.sha256(text.encode()).hexdigest(),
            status='value',value='Taza',quote=text)],usage={'model_calls':1,'fixture':True})
    return DocumentSession({'local':adapter},worker,lambda:'checkpoint-fixture-v1',attempt_budget=budget)


def child(root,mode):
    journal=CheckpointedDocumentSession(root/'journal',session(root,mode),contract='checkpoint-demo-v1')
    if mode=='after_result':
        original=journal._publish
        def publish(path,value):
            original(path,value)
            if path.name.endswith('.result.json'):os._exit(24)
        journal._publish=publish
    journal.execute(REQUEST_ID,REQUEST)
    raise AssertionError('Expected failpoint not reached')


def main():
    reports=[]
    for mode,exit_code in [('during_worker',23),('after_result',24)]:
        with tempfile.TemporaryDirectory(prefix='ocn-checkpoint-restart-') as tmp:
            root=Path(tmp);(root/'docs').mkdir();(root/'budget').mkdir()
            (root/'docs/d.txt').write_text('City Taza.')
            adapter=DocumentAdapter(root/'docs',root/'pins.json');adapter.bind('D','d.txt')
            budget=PersistentAttemptBudget.create(root/'budget',2)
            CheckpointedDocumentSession.create(root/'journal',session(root),contract='checkpoint-demo-v1')
            proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',str(root),mode],capture_output=True,text=True,timeout=20)
            assert proc.returncode==exit_code,proc.stderr
            assert budget.snapshot()['used']==1
            # Demonstrate that historical reconciliation does not read sources.
            (root/'docs/d.txt').unlink()
            reopened=CheckpointedDocumentSession(root/'journal',session(root),contract='checkpoint-demo-v1')
            receipt=reopened.recover(REQUEST_ID,REQUEST)
            if mode=='during_worker':
                assert receipt=={'state':'unresolved','historical':True}
                try:reopened.execute(REQUEST_ID,REQUEST)
                except RuntimeError as exc:assert 'Unresolved' in str(exc)
                else:raise AssertionError('Uncertain request executed again')
            else:
                assert receipt['state']=='completed' and receipt['historical']
                assert receipt['result']['values']=={'city':'Taza'}
                assert reopened.execute(REQUEST_ID,REQUEST)==receipt
            entries=(root/'worker_entries.jsonl').read_text().splitlines()
            assert len(entries)==1 and budget.snapshot()['used']==1
            reports.append(dict(failpoint=mode,exit_code=exit_code,state=receipt['state'],
                historical=receipt['historical'],worker_entries=1,quota_used=1,
                source_deleted_before_recovery=True,reexecution=False))
    print(json.dumps(dict(status='passed',fixture_workers=True,scenarios=reports,
        restart='parent reopens session after child termination',scope='Local checkpoint consistency, not exactly-once network execution or autonomous task resumption'),indent=2))

if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--child':child(Path(sys.argv[2]),sys.argv[3])
    elif len(sys.argv)==1:main()
    else:raise SystemExit('Usage: document_checkpoint_restart.py')
