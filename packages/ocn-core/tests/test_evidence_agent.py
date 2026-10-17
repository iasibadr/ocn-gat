import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.evidence_agent import EvidenceAgent
from ocn_core.evidence_revisions import Supersession

class EvidenceAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.docs=root/'docs';self.docs.mkdir()
        self.adapter=DocumentAdapter(self.docs,root/'bindings.json')
        for name,text in [('a','2 kg'),('b','2000 g')]:
            (self.docs/(name+'.txt')).write_text(text);self.adapter.bind(name,name+'.txt')
        self.fields={'mass':'Raw mass and unit.'}
        self.scales={'mass':dict(base_unit='g',factors={'kg':'1000','g':'1'})}
    def extract(self,q,fields,ident,text):
        return dict(observations=[dict(source_id=ident,field=f,sha256=hashlib.sha256(text.encode()).hexdigest(),status='value',value=text,quote=text) for f in fields],usage={})
    def run_agent(self,extractor=None,**kwargs):
        return EvidenceAgent(self.adapter,extractor or self.extract).answer('Mass?',self.fields,('a','b'),quantity_scales=self.scales,**kwargs)
    def test_exact_conversion_and_provenance(self):
        r=self.run_agent();self.assertEqual(r['values'],{'mass':'2000 g'});self.assertEqual(r['extractor_invocations'],2)
        self.assertEqual(r['conversions'][0]['original'],'2 kg');self.assertFalse(r['semantic_verification'])
    def test_relocates_during_extraction_and_returns_fresh_path(self):
        def extractor(q,f,i,t):
            if i=='b':(self.docs/'a.txt').rename(self.docs/'moved.txt')
            return self.extract(q,f,i,t)
        self.assertEqual(self.run_agent(extractor)['source_paths']['a'],'moved.txt')
    def test_changed_even_superseded_source_rejects_output(self):
        a=self.adapter.read('a');b=self.adapter.read('b');edge=Supersession('mass','a',a.sha256,'b',b.sha256)
        def extractor(q,f,i,t):
            if i=='b':(self.docs/'a.txt').write_text('3 kg')
            return self.extract(q,f,i,t)
        with self.assertRaises(ValueError):self.run_agent(extractor,host_supersessions=(edge,))
    def test_absence_blocks_without_partial_values(self):
        def extractor(q,f,i,t):
            r=self.extract(q,f,i,t)
            for row in r['observations']:row.update(status='absent',value=None,quote=None)
            return r
        r=self.run_agent(extractor);self.assertTrue(r['abstain']);self.assertEqual(r['values'],{})
    def test_omitted_field_is_not_silent_absence(self):
        with self.assertRaisesRegex(ValueError,'omitted'):self.run_agent(lambda *a:dict(observations=[],usage={}))
    def test_cross_source_injection_rejected(self):
        def extractor(q,f,i,t):
            r=self.extract(q,f,i,t);r['observations'][0]['source_id']='other';return r
        with self.assertRaisesRegex(ValueError,'scope'):self.run_agent(extractor)
    def test_fake_quantity_inside_real_quote_rejected(self):
        def extractor(q,f,i,t):
            r=self.extract(q,f,i,t);r['observations'][0]['value']='8 kg';return r
        with self.assertRaisesRegex(ValueError,'Raw quantity'):self.run_agent(extractor)
    def test_host_rule_invalid_before_extractor_call(self):
        mock=Mock();edge=Supersession('mass','a','0'*64,'b','0'*64)
        with self.assertRaises(ValueError):self.run_agent(mock,host_supersessions=(edge,))
        mock.assert_not_called()
    def test_source_budget_before_extractor_call(self):
        mock=Mock()
        with self.assertRaisesRegex(ValueError,'budget'):EvidenceAgent(self.adapter,mock,max_source_bytes=1).answer('Mass?',self.fields,('a','b'))
        mock.assert_not_called()
    def test_invalid_scale_before_extractor_call(self):
        mock=Mock();self.scales['mass']['factors']['kg']='-1'
        with self.assertRaises(ValueError):self.run_agent(mock)
        mock.assert_not_called()
    def test_extractor_cannot_mutate_field_contract(self):
        def extractor(q,f,i,t):
            result=self.extract(q,f,i,t);f.clear();return result
        self.assertEqual(self.run_agent(extractor)['values'],{'mass':'2000 g'})
        self.assertEqual(self.fields,{'mass':'Raw mass and unit.'})
if __name__=='__main__':unittest.main()
