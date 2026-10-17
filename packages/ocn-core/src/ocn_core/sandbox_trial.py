"""Explicit offline Linux trials for Python bridges; never a host-execution fallback."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from .agent_integration import Integration

OUTPUT_LIMIT=65536
HARNESS='''import json, resource
from pathlib import Path
for kind, limit in ((resource.RLIMIT_CPU,2),(resource.RLIMIT_AS,268435456),
                    (resource.RLIMIT_FSIZE,65536),(resource.RLIMIT_NOFILE,32),
                    (resource.RLIMIT_NPROC,16),(resource.RLIMIT_CORE,0)):
    resource.setrlimit(kind,(limit,limit))
request=json.loads(Path('/candidate/request.json').read_text())
namespace={'__name__':'gat_trial_agent','__file__':'/candidate/agent.py'}
exec(compile(Path('/candidate/agent.py').read_bytes(),'/candidate/agent.py','exec'),namespace)
factory=namespace[request['entrypoint']]
function=factory(request['model'])
if not callable(function):raise ValueError('Factory must return a callable')
result=function(request['question'],request['documents'])
print(json.dumps(result,ensure_ascii=False,allow_nan=False))
'''


def run_trial(integration, *, model, question, documents, timeout_seconds=5):
    """Execute a provided bridge on bounded inputs, returning untrusted output.

    Does not grant production permissions, certify semantics, or contact a model.
    The caller must compare the returned result against independent expectations.
    """
    if type(integration) is not Integration:raise ValueError('Prepared integration required')
    descriptor=integration.descriptor()
    if (type(model) is not str or not model.strip() or type(question) is not str
        or type(documents) is not list or type(timeout_seconds) is not int
        or not 1<=timeout_seconds<=10):raise ValueError('Invalid trial request')
    request=json.dumps(dict(model=model,question=question,documents=documents,
        entrypoint=descriptor['entrypoint']),ensure_ascii=False,allow_nan=False).encode()
    if len(request)>65536:raise ValueError('Trial fixture too large')
    bwrap=shutil.which('bwrap')
    if bwrap is None:raise RuntimeError('Bubblewrap required; host execution is forbidden')
    if not Path('/usr/bin/python3').is_file():raise RuntimeError('System Python required')
    with tempfile.TemporaryDirectory(prefix='gat-trial-') as directory:
        root=Path(directory);candidate=root/'candidate';candidate.mkdir()
        (candidate/'agent.py').write_bytes(integration.source)
        (candidate/'request.json').write_bytes(request)
        (candidate/'harness.py').write_text(HARNESS)
        command=[bwrap,'--unshare-all','--unshare-user','--disable-userns','--die-with-parent',
                 '--new-session','--cap-drop','ALL','--ro-bind','/usr','/usr']
        for name in ('/lib','/lib64'):
            if Path(name).exists():command.extend(['--ro-bind',name,name])
        command.extend(['--proc','/proc','--dev','/dev','--size','16777216','--tmpfs','/tmp',
            '--ro-bind',str(candidate),'/candidate','--chdir','/tmp','--clearenv',
            '--remount-ro','/','--remount-ro','/dev','--remount-ro','/proc',
            '--setenv','PATH','/usr/bin','/usr/bin/python3','-I','-S','/candidate/harness.py'])
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                close_fds=True,start_new_session=True,env={'PATH':'/usr/bin'})
            timed_out=False
            try:process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out=True
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)
            stdout.seek(0);out=stdout.read(OUTPUT_LIMIT+1)
            stderr.seek(0);err=stderr.read(OUTPUT_LIMIT+1)
        result=dict(status='failed',returncode=process.returncode,timed_out=timed_out,
            stdout_bytes=len(out),stderr_bytes=len(err),source_sha256=descriptor['sha256'])
        if timed_out:result['reason']='wall_timeout'
        elif len(out)>OUTPUT_LIMIT or len(err)>OUTPUT_LIMIT:result['reason']='output_limit'
        elif process.returncode!=0:result['reason']='sandbox_or_candidate_failure'
        else:
            try:
                def unique(pairs):
                    value=dict(pairs)
                    if len(value)!=len(pairs):raise ValueError('Duplicate output fields')
                    return value
                def reject_constant(value):raise ValueError('Invalid JSON constant')
                value=json.loads(out,object_pairs_hook=unique,parse_constant=reject_constant)
            except (ValueError,UnicodeError):result['reason']='invalid_json_output'
            else:result.update(status='completed',result=value)
        # Output from the tested code is untrusted; never interpret it as a tool call.
        if err:result['diagnostic']=err[:4096].decode('utf-8',errors='replace')
        return result


class IsolatedSynthesizer:
    """Offline bridge execution; DocumentAgent independently validates its output."""
    def __init__(self, integration, model, *, timeout_seconds=5):
        if type(integration) is not Integration:
            raise ValueError('Prepared integration required')
        integration.descriptor()
        self.integration=integration
        self.model=model
        self.timeout_seconds=timeout_seconds

    def __call__(self, question, documents):
        result=run_trial(self.integration,model=self.model,question=question,
                         documents=documents,timeout_seconds=self.timeout_seconds)
        if result['status']!='completed':
            raise RuntimeError('Isolated bridge failed: '+result.get('reason','unknown'))
        envelope=result['result']
        if (type(envelope) is not dict or set(envelope)!={'response','usage'}
            or type(envelope['usage']) is not dict):
            raise ValueError('Invalid isolated synthesis envelope')
        return dict(response=envelope['response'],usage=dict(
            candidate_reported=envelope['usage'],execution='offline_bubblewrap',
            source_sha256=result['source_sha256'],host_model_calls=0))
