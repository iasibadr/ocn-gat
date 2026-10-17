from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest

from ocn_core.persistent_extraction import PersistentExtractionCache


class PersistentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'cache.sqlite';self.calls=[];self.version='1'

    def worker(self,q,fields,ident,text):
        self.calls.append(ident)
        return dict(observations=[dict(source_id=ident,field=f,sha256=hashlib.sha256(text.encode()).hexdigest(),
                    status='value',value=text,quote=text) for f in fields],usage=dict(model_calls=1))

    def cache(self,**kwargs): return PersistentExtractionCache(self.path,self.worker,lambda:self.version,**kwargs)
    def request(self,cache,text='2 kg',ident='a'): return cache('Mass?',{'mass':'Raw'},ident,text)

    def test_reopens_and_returns_independent_data(self):
        c=self.cache();self.request(c)['observations'].clear()
        r=self.request(self.cache());self.assertTrue(r['usage']['persistent_hit'])
        self.assertEqual(len(r['observations']),1);self.assertEqual(len(self.calls),1)

    def test_content_and_worker_version_require_new_calls(self):
        c=self.cache();self.request(c);self.request(c,'3 kg');self.version='2';self.request(c,'3 kg')
        self.assertEqual(len(self.calls),3)

    def test_reuse_limit_survives_reopening(self):
        self.request(self.cache(max_reuses=1));self.request(self.cache(max_reuses=1))
        self.request(self.cache(max_reuses=1));self.assertEqual(len(self.calls),2)

    def test_size_and_entry_bounds_after_reopening(self):
        c=self.cache(max_entries=2,max_bytes=2048)
        for i in range(5):self.request(c,ident=str(i))
        self.assertEqual(c.stats()['entries'],2)
        self.assertLessEqual(c.stats()['serialized_bytes'],2048)
        self.assertEqual(self.cache(max_entries=1).stats()['entries'],1)

    def test_corrupt_evidence_not_emitted(self):
        self.request(self.cache())
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE entries SET payload=?",(b'{"observations":[],"usage":{}}',))
        with self.assertRaisesRegex(ValueError,'omitted'):self.request(self.cache())

    def test_no_sqlite_lock_during_worker(self):
        gate=Barrier(2,timeout=3)
        def worker(*args):gate.wait();return self.worker(*args)
        c=PersistentExtractionCache(self.path,worker,lambda:'1')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.request,c,ident=str(i)) for i in range(2)]
            for f in futures:self.assertEqual(len(f.result()['observations']),1)
        self.assertEqual(c.stats()['entries'],2)

    def test_revision_change_does_not_persist(self):
        def worker(*args):self.version='2';return self.worker(*args)
        c=PersistentExtractionCache(self.path,worker,lambda:self.version)
        with self.assertRaisesRegex(ValueError,'revision changed'):self.request(c)
        self.assertEqual(c.stats()['entries'],0)

    def test_unknown_schema_and_symlink_rejected(self):
        self.cache()
        with sqlite3.connect(self.path) as db:db.execute('PRAGMA user_version=9')
        with self.assertRaises(ValueError):self.cache()
        link=self.path.with_name('link');link.symlink_to(self.path)
        with self.assertRaises(ValueError):PersistentExtractionCache(link,self.worker,lambda:'1')


if __name__=='__main__':unittest.main()
