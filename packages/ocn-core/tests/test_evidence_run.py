import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ocn_core.gat import create, set_paused
from ocn_core.evidence_run import run_evidence


class EvidenceRunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name); self.docs=root/'docs'; self.docs.mkdir(); self.instance=root/'instance'
        for name,text in [('a','2 kg'),('b','2000 g')]: (self.docs/f'{name}.txt').write_text(text)
        create(self.instance,self.docs,{'a':'a.txt','b':'b.txt'},'Mass?')
        self.fields={'mass':'Copy raw mass'}
        self.scales={'mass':dict(base_unit='g',factors={'g':'1','kg':'1000'})}

    def worker(self,q,fields,ident,text):
        return dict(observations=[dict(source_id=ident,field=f,sha256=hashlib.sha256(text.encode()).hexdigest(),
                    status='value',value=text,quote=text) for f in fields],usage=dict(model_calls=1))

    def test_both_modes_and_moved_sources(self):
        for mode in ('serial','organ'):
            result=run_evidence(self.instance,self.fields,quantity_scales=self.scales,mode=mode,worker=self.worker)
            self.assertEqual(result['result']['values'],{'mass':'2000 g'})
            self.assertEqual(result['worker_calls'],2)
        (self.docs/'a.txt').rename(self.docs/'moved.txt')
        result=run_evidence(self.instance,self.fields,quantity_scales=self.scales,mode='organ',worker=self.worker)
        self.assertEqual(result['result']['source_paths']['a'],'moved.txt')

    def test_persistent_memory_shared_between_execution_modes(self):
        initial=run_evidence(self.instance,self.fields,quantity_scales=self.scales,worker=self.worker,
                             persist_memory=True,worker_revision='test-worker-v1')
        repeated=run_evidence(self.instance,self.fields,quantity_scales=self.scales,mode='organ',
                              worker=self.worker,persist_memory=True,worker_revision='test-worker-v1')
        self.assertEqual(initial['worker_calls'],2)
        self.assertEqual(repeated['worker_calls'],0)
        self.assertEqual(repeated['persistent_memory']['hits'],2)

    def test_injected_persistent_worker_needs_revision(self):
        with self.assertRaisesRegex(ValueError,'revision'):
            run_evidence(self.instance,self.fields,worker=self.worker,persist_memory=True)

    def test_paused_before_worker(self):
        worker=Mock(); set_paused(self.instance,True)
        with self.assertRaises(RuntimeError): run_evidence(self.instance,self.fields,worker=worker)
        worker.assert_not_called()

    def test_budget_cannot_omit_sources(self):
        worker=Mock()
        with self.assertRaisesRegex(ValueError,'budget'):
            run_evidence(self.instance,self.fields,max_model_calls=1,worker=worker)
        worker.assert_not_called()

    def test_invalid_fields_before_worker(self):
        worker=Mock()
        with self.assertRaises(ValueError): run_evidence(self.instance,{},worker=worker)
        worker.assert_not_called()

    def test_unauthorized_content_not_read_as_new_authority(self):
        (self.docs/'a.txt').write_text('9 kg'); worker=Mock()
        with self.assertRaises(ValueError): run_evidence(self.instance,self.fields,worker=worker)
        worker.assert_not_called()

    def test_no_bridge_bypass(self):
        # Exercise the execution boundary after loading an adapted format.
        from ocn_core.gat import load, ADAPTED_FORMAT
        from unittest.mock import patch
        root, config=load(self.instance); config['format']=ADAPTED_FORMAT
        worker=Mock()
        with patch('ocn_core.gat.load',return_value=(root,config)):
            with self.assertRaisesRegex(ValueError,'ordinary'):
                run_evidence(self.instance,self.fields,worker=worker)
        worker.assert_not_called()


if __name__=='__main__': unittest.main()
