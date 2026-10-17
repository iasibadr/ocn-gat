"""Crash/restart quota demonstration: fixture workers, explicit host restarts.

No LLM or network. All files are synthetic and kept in a temporary directory.
This demonstrates durable quota, not recovery of an interrupted task's result.
"""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession
from ocn_core.model_budget import PersistentAttemptBudget


def child(root,mode):
    budget=PersistentAttemptBudget(root/'budget',2)
    adapter=DocumentAdapter(root/'docs',root/'pins.json')
    def worker(question,fields,identity,text):
        with (root/'worker_entries.jsonl').open('a') as log:
            log.write(json.dumps({'mode':mode,'reserved_used':budget.snapshot()['used']})+'\n')
            log.flush();os.fsync(log.fileno())
        if mode=='crash':os._exit(23)
        return dict(observations=[dict(source_id=identity,field='city',sha256=hashlib.sha256(text.encode()).hexdigest(),
            status='value',value='Taza',quote='City Taza.')],usage={'model_calls':1,'fixture':True})
    session=DocumentSession({'local':adapter},worker,lambda:'restart-fixture-v1',attempt_budget=budget,max_model_calls=2)
    try:answer=session.answer('City?',{'city':'Copy city'},('D',))
    except RuntimeError as exc:
        if 'Persistent model call budget exhausted' not in str(exc):raise
        print(json.dumps({'status':'budget_denied','local_calls':session.calls,'budget':budget.snapshot()}))
        return
    print(json.dumps({'status':'answered','values':answer['values'],'local_calls':session.calls,'budget':budget.snapshot()}))


def main():
    with tempfile.TemporaryDirectory(prefix='ocn-document-restart-') as tmp:
        root=Path(tmp);(root/'docs').mkdir();(root/'budget').mkdir()
        (root/'docs/d.txt').write_text('City Taza.')
        adapter=DocumentAdapter(root/'docs',root/'pins.json');adapter.bind('D','d.txt')
        budget=PersistentAttemptBudget.create(root/'budget',2)
        def launch(mode):
            return subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',str(root),mode],capture_output=True,text=True,timeout=20)
        crash=launch('crash');assert crash.returncode==23,crash.stderr
        assert budget.snapshot()['used']==1
        resumed=launch('normal');assert resumed.returncode==0,resumed.stderr
        answer=json.loads(resumed.stdout);assert answer['values']=={'city':'Taza'} and answer['budget']['used']==2
        denied=launch('normal');assert denied.returncode==0,denied.stderr
        refusal=json.loads(denied.stdout);assert refusal['status']=='budget_denied' and refusal['local_calls']==0
        entries=[json.loads(line) for line in (root/'worker_entries.jsonl').read_text().splitlines()]
        assert entries==[{'mode':'crash','reserved_used':1},{'mode':'normal','reserved_used':2}]
        print(json.dumps(dict(status='passed',fixture_workers=True,processes=3,worker_entries=2,
            crash_exit_code=23,reservation_survived_crash=True,restarted_answer=answer['values'],
            exhausted_restart_denied_before_worker=True,persistent_budget=budget.snapshot(),
            restart='explicit parent process, not autonomous supervisor',
            scope='Quota persistence only; interrupted task result and feedback are not recovered'),indent=2))

if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--child':child(Path(sys.argv[2]),sys.argv[3])
    elif len(sys.argv)==1:main()
    else:raise SystemExit('Usage: document_budget_restart.py')
