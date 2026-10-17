import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from ocn_core import gat
from ocn_core.agent_integration import Integration
from unittest.mock import patch,Mock
from ocn_core.candidate_adoption import adopt,rollback
from ocn_core.cumulative_adoption import adopt_cumulative,combine
from ocn_core.bridge_repair import repair


def bridge(ids):
    return Integration(('def build_synthesizer(model):\n'
        '    def run(question, documents):\n'
        '        for d in documents:\n'
        f'            if question in {ids!r} and d["document_id"] == question:\n'
        '                return {"response":{"answer":d["text"],"abstain":False,"citations":[{"document_id":d["document_id"],"quote":d["text"]}]},"usage":{}}\n'
        '        return {"response":{"answer":"Unknown","abstain":True,"citations":[]},"usage":{}}\n'
        '    return run\n').encode(),'build_synthesizer')

def suite(ident,text):
    return dict(format='gat.acceptance-suite.v1',cases=[dict(id=ident,question=ident,documents=[dict(document_id=ident,text=text)],
        expected=dict(response=dict(answer=text,abstain=False,citations=[dict(document_id=ident,quote=text)])))])

class CumulativeAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);docs=root/'docs';docs.mkdir();(docs/'a.md').write_text('Alpha');(docs/'b.md').write_text('Beta')
        self.instance=root/'agent';self.old=suite('a','Alpha');self.new=suite('b','Beta')
        empty=bridge(())
        gat.create(self.instance,docs,{'a':'a.md','b':'b.md'},'a',model='offline',integration=empty,isolated=True)
        self.first=bridge(('a',))
        self.assertTrue(adopt(self.instance,self.first,self.old,empty.descriptor()['sha256'])['adopted'])
    def test_new_skill_cannot_erase_retained_skill(self):
        before=(self.instance/'instance.json').read_bytes()
        result=adopt_cumulative(self.instance,bridge(('b',)),self.new,self.first.descriptor()['sha256'])
        self.assertFalse(result['adopted']);self.assertEqual(result['cumulative_cases'],2)
        self.assertEqual((self.instance/'instance.json').read_bytes(),before)
        self.assertEqual(gat.run(self.instance,question='a')['answer'],'Alpha')
    def test_retains_both_skills_across_reopen_and_following_adoption(self):
        both=bridge(('a','b'))
        result=adopt_cumulative(self.instance,both,self.new,self.first.descriptor()['sha256'])
        self.assertTrue(result['adopted'])
        self.assertEqual(gat.run(self.instance,question='a')['answer'],'Alpha')
        self.assertEqual(gat.run(self.instance,question='b')['answer'],'Beta')
        again=adopt_cumulative(self.instance,bridge(('b',)),self.new,both.descriptor()['sha256'])
        self.assertFalse(again['adopted']);self.assertEqual(again['cumulative_cases'],2)
    def test_missing_or_changed_retained_evidence_refuses(self):
        config=json.loads((self.instance/'instance.json').read_text());digest=config['evolution']['suite_sha256']
        path=self.instance/'acceptance-suites'/(digest+'.json');raw=path.read_bytes();path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError,'integrity'):adopt_cumulative(self.instance,bridge(('a','b')),self.new,self.first.descriptor()['sha256'])
        path.unlink()
        with self.assertRaises(FileNotFoundError):adopt_cumulative(self.instance,bridge(('a','b')),self.new,self.first.descriptor()['sha256'])
    def test_concurrent_rollback_roundtrip_cannot_change_preservation_lineage(self):
        def raced(*args,**kwargs):
            first=rollback(self.instance,self.first.descriptor()['sha256'])
            rollback(self.instance,first['integration']['sha256'])
            return adopt(*args,**kwargs)
        with patch('ocn_core.cumulative_adoption.adopt',side_effect=raced):
            with self.assertRaisesRegex(ValueError,'lineage changed'):
                adopt_cumulative(self.instance,bridge(('a','b')),self.new,self.first.descriptor()['sha256'])

    def test_cli_rejects_forgetting_then_accepts_cumulative_candidate(self):
        source=self.instance.parent/'candidate.py';suite_path=self.instance.parent/'new-suite.json'
        suite_path.write_text(json.dumps(self.new));source.write_bytes(bridge(('b',)).source)
        command=[sys.executable,'-m','ocn_core.gat','adopt',str(self.instance),'--agent-file',str(source),
                 '--suite',str(suite_path),'--expected-current-sha256',self.first.descriptor()['sha256'],'--preserve-acceptance']
        before=(self.instance/'instance.json').read_bytes()
        rejected=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(rejected.returncode,0,rejected.stderr)
        self.assertFalse(json.loads(rejected.stdout)['adopted'])
        self.assertEqual((self.instance/'instance.json').read_bytes(),before)
        source.write_bytes(bridge(('a','b')).source)
        accepted=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(accepted.returncode,0,accepted.stderr)
        result=json.loads(accepted.stdout)
        self.assertTrue(result['adopted']);self.assertEqual(result['cumulative_cases'],2)
        for ident,answer in [('a','Alpha'),('b','Beta')]:
            completed=subprocess.run([sys.executable,'-m','ocn_core.gat','run',str(self.instance),'--question',ident],capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertEqual(json.loads(completed.stdout)['answer'],answer)

    def test_repair_uses_retained_cases_without_exposing_expected_texts(self):
        for name,ids,accepted in [('forget',('b',),False),('keep',('a','b'),True)]:
            proposer=Mock(return_value=(bridge(ids),{'model_calls':0}))
            result=repair(self.instance,'Keep existing behavior and add b.',self.new,proposer,self.instance.parent/name,preserve_acceptance=True)
            self.assertEqual(result['decision']['adopted'],accepted)
            self.assertEqual(result['decision']['candidate']['cases'],2)
            proposer.assert_called_once()
            self.assertEqual(len(proposer.call_args.args),3)
            self.assertFalse(proposer.call_args.kwargs)
        self.assertEqual(gat.run(self.instance,question='a')['answer'],'Alpha')
        self.assertEqual(gat.run(self.instance,question='b')['answer'],'Beta')
    def test_repair_missing_retained_suite_never_calls_designer(self):
        digest=json.loads((self.instance/'instance.json').read_text())['evolution']['suite_sha256']
        (self.instance/'acceptance-suites'/(digest+'.json')).unlink()
        proposer=Mock()
        with self.assertRaises(FileNotFoundError):
            repair(self.instance,'Contract',self.new,proposer,self.instance.parent/'audit',preserve_acceptance=True)
        proposer.assert_not_called()
    def test_repair_lineage_change_during_proposal_prevents_adoption(self):
        def propose(*args):
            first=rollback(self.instance,self.first.descriptor()['sha256'])
            rollback(self.instance,first['integration']['sha256'])
            return bridge(('a','b')),{'model_calls':0}
        proposer=Mock(side_effect=propose)
        with self.assertRaisesRegex(ValueError,'lineage changed'):
            repair(self.instance,'Contract',self.new,proposer,self.instance.parent/'audit',preserve_acceptance=True)
        proposer.assert_called_once()
    def test_repair_cli_routes_preservation_to_real_guard(self):
        from ocn_core.bridge_repair import LocalBridgeRepairer
        suite_path=self.instance.parent/'incoming.json';suite_path.write_text(json.dumps(self.new))
        calls=[]
        class FixtureRepairer(LocalBridgeRepairer):
            def __call__(self,*args,**kwargs):
                calls.append(args)
                return bridge(('b',)),{'model_calls':0}
        args=['gat','repair',str(self.instance),'--contract','Add b without losing a.',
              '--suite',str(suite_path),'--designer-model','fixture-only','--output',str(self.instance.parent/'cli-audit'),'--preserve-acceptance']
        output=io.StringIO()
        with patch.object(sys,'argv',args),patch('ocn_core.bridge_repair.LocalBridgeRepairer',FixtureRepairer),redirect_stdout(output):
            gat.main()
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'rejected');self.assertEqual(len(calls),1)
        self.assertEqual(result['decision']['candidate']['cases'],2)

    def test_union_deduplicates_exact_cases_but_never_silently_discards_overflow(self):
        renamed=json.loads(json.dumps(self.old));renamed['cases'][0]['id']='different-label'
        self.assertEqual(len(combine(self.old,renamed)['cases']),1)
        sixteen=dict(format='gat.acceptance-suite.v1',cases=[suite(str(i),'Text')['cases'][0] for i in range(16)])
        with self.assertRaises(ValueError):combine(sixteen,self.old)

if __name__=='__main__':unittest.main()
