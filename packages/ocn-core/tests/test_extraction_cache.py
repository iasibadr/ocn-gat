import hashlib
import unittest
from ocn_core.extraction_cache import ExtractionCache

class CacheTests(unittest.TestCase):
    def setUp(self):self.calls=0;self.revision='model-code-v1';self.fields={'value':'Extract the value.'}
    def extract(self,q,f,i,t):
        self.calls+=1
        return dict(observations=[dict(source_id=i,field=k,sha256=hashlib.sha256(t.encode()).hexdigest(),status='value',value=t,quote=t) for k in f],usage=dict(model_calls=1,input_tokens=10,output_tokens=5))
    def cache(self,**kwargs):return ExtractionCache(self.extract,lambda:self.revision,**kwargs)
    def call(self,c,**kwargs):return c(kwargs.get('q','What?'),kwargs.get('fields',self.fields),kwargs.get('id','s'),kwargs.get('text','hello'))
    def test_hit_counts_no_new_inference_and_retains_old_usage(self):
        c=self.cache();self.call(c);r=self.call(c)
        self.assertEqual(self.calls,1);self.assertEqual(r['usage']['model_calls'],0)
        self.assertEqual(r['usage']['reused_usage']['model_calls'],1)
    def test_each_identity_change_invalidates(self):
        for change in (dict(q='Why?'),dict(fields={'value':'Other description'}),dict(id='other'),dict(text='changed')):
            c=self.cache();before=self.calls;self.call(c);self.call(c,**change);self.assertEqual(self.calls-before,2)
        c=self.cache();self.call(c);before=self.calls;self.revision='v2';self.call(c);self.assertEqual(self.calls,before+1)
    def test_periodic_refresh(self):
        c=self.cache(max_reuses=2)
        for _ in range(4):self.call(c)
        self.assertEqual(self.calls,2);self.assertEqual(c.stats()['hits'],2)
    def test_capacity_eviction(self):
        c=self.cache(max_entries=1);self.call(c);self.call(c,text='other');self.call(c)
        self.assertEqual(self.calls,3);self.assertEqual(c.stats()['entries'],1)
    def test_oversized_entries_bypass_storage(self):
        c=self.cache(max_bytes=1);self.call(c);self.call(c)
        self.assertEqual(self.calls,2);self.assertEqual(c.stats()['serialized_bytes'],0)
    def test_returned_mutation_cannot_poison_cache(self):
        c=self.cache();r=self.call(c);r['observations'][0]['value']='poison'
        r=self.call(c);self.assertEqual(r['observations'][0]['value'],'hello')
        r['observations'].clear();self.assertEqual(len(self.call(c)['observations']),1)
    def test_invalid_extraction_never_stored(self):
        def bad(*args):return dict(observations=[],usage={})
        c=ExtractionCache(bad,lambda:'v')
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'omitted'):self.call(c)
        self.assertEqual(c.stats()['entries'],0)
    def test_revision_change_during_extraction_blocks_storage(self):
        def changed(*args):self.revision='changed';return self.extract(*args)
        c=ExtractionCache(changed,lambda:self.revision)
        with self.assertRaisesRegex(ValueError,'revision changed'):self.call(c)
        self.assertEqual(c.stats()['entries'],0)
    def test_clear_removes_entries(self):
        c=self.cache();self.call(c);c.clear();self.call(c)
        self.assertEqual(self.calls,2);self.assertEqual(c.stats()['entries'],1)
    def test_field_order_is_part_of_identity(self):
        c=self.cache();self.call(c,fields={'a':'A','b':'B'});self.call(c,fields={'b':'B','a':'A'})
        self.assertEqual(self.calls,2)
if __name__=='__main__':unittest.main()
