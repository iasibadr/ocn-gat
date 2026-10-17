import argparse,importlib.util,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('ocn_document_session_example',
    Path(__file__).resolve().parents[1]/'examples/document_session.py')
CLI=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(CLI)

class Worker:
    def __init__(self,model,max_calls):
        self.model_digest='fixture-digest';self.max_calls=max_calls;self.log=[]
    @property
    def calls(self):return len(self.log)
    def attempts(self):return list(self.log)
    def revision(self):return 'fixture-worker-v1'
    def charge(self,stage):
        if self.calls>=self.max_calls:raise RuntimeError('Worker call budget exhausted')
        self.log.append(dict(stage=stage))
    def select(self,r):
        self.charge('select');return {f:[r['paragraphs'][0]['id']] for f in r['fields']}
    def answer(self,r):
        self.charge('answer')
        return {f:dict(status='supported',answer=r['paragraphs'][0]['text'],references=[r['paragraphs'][0]['id']]) for f in r['fields']}

def line(ident='q1',**changes):
    return json.dumps(dict(id=ident,question='Jour pour LT73 ?',fields={'jour':'Jour'},**changes))+'\n'

class SessionCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'a.md').write_text('LT73 lundi.')
    def args(self,**changes):
        options=dict(model='fixture',habitat=self.root,document=['a=a.md'],selection='full',
            live_identity=False,max_requests=8,max_model_calls=16)
        options.update(changes);return argparse.Namespace(**options)
    def run_cli(self,stream,**changes):
        output=io.StringIO()
        with patch.object(CLI,'LocalEvidenceContextWorker',Worker):
            code=CLI.serve(self.args(**changes),stream,output)
        return code,[json.loads(row) for row in output.getvalue().splitlines()]

    def test_same_live_session_survives_copies_then_blocks_tampering(self):
        (self.root/'b.md').write_text('LT73 lundi.');root=self.root
        class Input:
            index=0
            def readline(self,limit):
                self.index+=1
                if self.index==2:
                    (root/'a.md').rename(root/'first.md');(root/'b.md').rename(root/'second.md')
                if self.index==3:(root/'second.md').write_text('Changed')
                return line('q'+str(self.index)) if self.index<=3 else ''
        before=set(os.listdir('/proc/self/fd'))
        code,events=self.run_cli(Input(),document=['a=a.md','b=b.md'],live_identity=True,selection='unique-coverage')
        self.assertEqual(code,0);self.assertEqual([e['event'] for e in events],['ready','answer','answer','error','closed'])
        self.assertTrue(events[2]['receipt']['session']['selection_cache_hit'])
        self.assertEqual(events[2]['receipt']['sources']['a']['path'],'first.md')
        self.assertEqual(events[3]['new_model_calls'],0)
        self.assertIn('Pinned version changed',events[3]['error'])
        self.assertEqual(events[-1]['model_calls'],2)
        self.assertEqual(set(os.listdir('/proc/self/fd')),before)

    def test_invalid_duplicate_id_and_extra_authority_consume_no_calls(self):
        text='not json\n'+line()+line()+json.dumps(dict(id='q2',question='x',fields={'f':'x'},update_version=True))+'\n'
        _,events=self.run_cli(io.StringIO(text))
        self.assertEqual([e['event'] for e in events],['ready','error','answer','error','error','closed'])
        self.assertEqual(events[-1]['model_calls'],1);self.assertEqual(events[-1]['received'],4)

    def test_nonfinite_duplicate_json_and_deep_input_rejected(self):
        text='{"id":"q","id":"other","question":"x","fields":{}}\n'
        text+='{"id":"q2","question":NaN,"fields":{}}\n'
        text+='['*2000+']'*2000+'\n'
        _,events=self.run_cli(io.StringIO(text))
        self.assertEqual(events[-1]['model_calls'],0)
        self.assertEqual(sum(e['event']=='error' for e in events),3)

    def test_request_and_input_limits(self):
        _,events=self.run_cli(io.StringIO('bad\nbad\n'+line()),max_requests=2)
        self.assertEqual(events[-1]['reason'],'request_limit');self.assertEqual(events[-1]['received'],2)
        _,events=self.run_cli(io.StringIO('x'*32769+'\n'+line()),live_identity=True)
        self.assertEqual(events[-1]['reason'],'input_limit');self.assertEqual(events[-1]['model_calls'],0)

    def test_model_budget_shared_across_inputs(self):
        _,events=self.run_cli(io.StringIO(line('q1')+line('q2')+line('q3')),max_model_calls=2)
        self.assertEqual(events[-1]['reason'],'model_call_limit');self.assertEqual(events[-1]['received'],2)

    def test_llm_selection_cache_uses_three_calls_for_two_answers(self):
        _,events=self.run_cli(io.StringIO(line('q1')+line('q2')),selection='llm',max_model_calls=3)
        self.assertEqual(events[1]['new_model_calls'],2);self.assertEqual(events[2]['new_model_calls'],1)
        self.assertTrue(events[2]['receipt']['session']['selection_cache_hit'])
        self.assertEqual(events[-1]['reason'],'model_call_limit')

    def test_failed_setup_and_empty_stream(self):
        code,events=self.run_cli(io.StringIO(''),document=['a=missing.md'],live_identity=True)
        self.assertEqual(code,1);self.assertEqual(events[0]['event'],'fatal')
        code,events=self.run_cli(io.StringIO(''),live_identity=True)
        self.assertEqual(code,0);self.assertEqual(events[-1]['reason'],'eof')
        self.assertEqual(events[-1]['model_calls'],0)

if __name__=='__main__':unittest.main()
