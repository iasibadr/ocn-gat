import argparse,importlib.util,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ocn_core.local_evidence_context import LocalEvidenceContextWorker
SPEC=importlib.util.spec_from_file_location('window_session_cli',Path(__file__).resolve().parents[1]/'examples/document_session.py')
CLI=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(CLI)

def line(ident,question='Jour LT73 ?'):
    return json.dumps(dict(id=ident,question=question,fields={'jour':'Jour LT73'}))+'\n'

class WindowCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.text='LT73 lundi. '+('Inventaire décoratif. '*30)
        (self.root/'a.md').write_text(self.text)
    def run_cli(self,stream,**changes):
        args=dict(model='fixture',habitat=self.root,document=['a=a.md'],selection='source-windows',live_identity=True,max_requests=8,max_model_calls=4,max_passages=128)
        args.update(changes);out=io.StringIO();workers=[]
        def factory(model,max_calls):
            w=LocalEvidenceContextWorker(model,max_calls=max_calls);workers.append(w)
            def capacity(p):
                if sum(len(x['text']) for x in p['paragraphs'])>200:raise ValueError('Prompt exceeds maximum conservative context allowance')
                return {}
            def answer(p):
                capacity(p)
                if w.calls>=w.max_calls:raise RuntimeError('Model budget exhausted')
                w._attempts.append(dict(stage='answer'))
                if 'absent' in p['question']:
                    return {'jour':dict(status='unknown',answer=None,references=[p['paragraphs'][0]['id']])}
                return {'jour':dict(status='supported',answer='lundi',references=[p['paragraphs'][0]['id']])}
            w.context_plan=capacity;w.answer=answer;return w
        with patch('ocn_core.local_evidence_context.require_model',return_value={'digest':'fixture'}),patch.object(CLI,'LocalEvidenceContextWorker',factory):
            code=CLI.serve(argparse.Namespace(**args),stream,out)
        return code,[json.loads(s) for s in out.getvalue().splitlines()],workers
    def test_actual_cli_routes_moves_and_blocks_change(self):
        (self.root/'b.md').write_text(self.text);root=self.root
        class Input:
            n=0
            def readline(self,limit):
                self.n+=1
                if self.n==2:
                    (root/'a.md').rename(root/'first.md');(root/'b.md').rename(root/'second.md')
                if self.n==3:(root/'second.md').write_text('Changed')
                return line(str(self.n)) if self.n<=3 else ''
        code,events,_=self.run_cli(Input(),document=['a=a.md','b=b.md'])
        self.assertEqual(code,0);self.assertEqual([r['event'] for r in events],['ready','answer','answer','error','closed'])
        self.assertEqual(events[1]['receipt']['context_routing']['routes'],['full','source-windows'])
        self.assertEqual(events[2]['receipt']['sources']['a']['path'],'first.md')
        self.assertEqual(events[3]['new_model_calls'],0);self.assertIn('Pinned version changed',events[3]['error'])
        self.assertEqual(events[-1]['model_calls'],2);self.assertEqual(events[0]['max_passages'],128)
    def test_null_unknown_is_normalized(self):
        _,events,_=self.run_cli(io.StringIO(line('q','Nom absent LT73 ?')))
        receipt=events[1]['receipt'];self.assertEqual(receipt['fields']['jour']['references'],[])
        self.assertTrue(receipt['withheld_unknown_references']);self.assertIsNone(receipt['fields']['jour']['answer'])
    def test_invalid_line_does_not_repeat_old_routing(self):
        _,events,_=self.run_cli(io.StringIO(line('q')+'not json\n'))
        self.assertIsNone(events[2]['context_routing']);self.assertEqual(events[2]['new_model_calls'],0)
    def test_passage_limit_prevents_generation(self):
        _,events,workers=self.run_cli(io.StringIO(line('q')),max_passages=1)
        self.assertEqual(events[1]['event'],'error');self.assertIn('Paragraph budget',events[1]['error'])
        self.assertEqual(workers[0].calls,0)
    def test_invalid_limits_fail_before_worker(self):
        for changes in ({'max_requests':65},{'max_passages':2049},{'max_passages':True},{'selection':'invented'}):
            code,events,workers=self.run_cli(io.StringIO(''),**changes)
            self.assertEqual(code,1);self.assertEqual(events[0]['event'],'fatal');self.assertEqual(workers,[])
    def test_shared_call_budget_stops_session(self):
        _,events,_=self.run_cli(io.StringIO(line('q1')+line('q2')+line('q3')),max_model_calls=2)
        self.assertEqual(events[-1]['reason'],'model_call_limit');self.assertEqual(events[-1]['received'],2)

if __name__=='__main__':unittest.main()
