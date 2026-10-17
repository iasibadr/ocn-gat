"""Bounded version-keyed extraction memory for a trusted local instance.

SQLite transactions protect concurrent cells. No database lock is held while the
worker runs. Concurrent identical misses may duplicate inference; all are charged.
Bounds cover serialized entries, not SQLite files or RAM. No semantic certification.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import Lock

from .evidence_coverage import assess_coverage


class PersistentExtractionCache:
    def __init__(self, path, worker, revision, *, max_entries=24, max_bytes=196608, max_reuses=8):
        if not callable(worker) or not callable(revision):
            raise ValueError('Worker and revision callback required')
        for n, cap in ((max_entries,256),(max_bytes,4194304),(max_reuses,1024)):
            if type(n) is not int or not 1 <= n <= cap: raise ValueError('Invalid persistent memory bound')
        self.path=Path(path).absolute()
        if self.path.is_symlink(): raise ValueError('Memory symlink forbidden')
        if not self.path.exists():
            fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        self.worker,self.revision=worker,revision
        self.max_entries,self.max_bytes,self.max_reuses=max_entries,max_bytes,max_reuses
        self._lock=Lock();self.hits=self.misses=self.evictions=0
        with self._connection() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
                raise ValueError('Unsupported evidence memory version')
            db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, payload BLOB NOT NULL, uses INTEGER NOT NULL, touched INTEGER NOT NULL)')
            db.execute('PRAGMA user_version=1')
            db.execute('BEGIN IMMEDIATE')
            self._trim(db)

    @contextmanager
    def _connection(self):
        if self.path.is_symlink(): raise ValueError('Memory symlink forbidden')
        db=sqlite3.connect(self.path,timeout=10)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback();raise
        finally: db.close()

    def _trim(self,db):
        while True:
            count,size=db.execute('SELECT count(*),coalesce(sum(length(payload)+length(key)),0) FROM entries').fetchone()
            if count<=self.max_entries and size<=self.max_bytes: return
            db.execute('DELETE FROM entries WHERE key=(SELECT key FROM entries ORDER BY touched,key LIMIT 1)')
            with self._lock: self.evictions+=1

    def _revision(self):
        value=self.revision()
        if type(value) is not str or not value.strip() or len(value.encode())>4096:
            raise ValueError('Bounded worker revision required')
        return value

    @staticmethod
    def _validate(value,fields,ident,text):
        if type(value) is not dict or set(value)!={'observations','usage'} or type(value['usage']) is not dict:
            raise ValueError('Invalid stored extraction envelope')
        assess_coverage(tuple(fields),{ident:text},value['observations'])
        if {r['field'] for r in value['observations']}!=set(fields):
            raise ValueError('Extraction omitted fields')

    def __call__(self,question,fields,ident,text):
        if type(question) is not str or not question.strip() or len(question.encode())>4096:
            raise ValueError('Bounded question required')
        if type(fields) is not dict or any(type(v) is not str or not v.strip() or len(v.encode())>1024 for v in fields.values()):
            raise ValueError('Field descriptions required')
        assess_coverage(tuple(fields),{ident:text},[])
        revision=self._revision()
        key=hashlib.sha256(json.dumps([revision,question,list(fields.items()),ident,
            hashlib.sha256(text.encode()).hexdigest()],ensure_ascii=False).encode()).hexdigest()
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload,uses FROM entries WHERE key=?',(key,)).fetchone()
            if row is not None:
                payload,uses=row
                if not isinstance(payload,bytes) or len(payload)+len(key)>self.max_bytes or type(uses) is not int or uses<0:
                    raise ValueError('Invalid persistent entry')
                if uses<self.max_reuses:
                    value=json.loads(payload)
                    self._validate(value,fields,ident,text)
                    tick=db.execute('SELECT coalesce(max(touched),0)+1 FROM entries').fetchone()[0]
                    db.execute('UPDATE entries SET uses=uses+1,touched=? WHERE key=?',(tick,key))
                    with self._lock:self.hits+=1
                    return dict(observations=value['observations'],usage=dict(cache_hit=True,persistent_hit=True,
                        model_calls=0,input_tokens=0,output_tokens=0,reused_usage=value['usage'],extractor_revision=revision))
                db.execute('DELETE FROM entries WHERE key=?',(key,))
                with self._lock:self.evictions+=1
        with self._lock:self.misses+=1
        value=self.worker(question,dict(fields),ident,text)
        if self._revision()!=revision: raise ValueError('Worker revision changed during extraction')
        self._validate(value,fields,ident,text)
        payload=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        if len(payload)+len(key)<=self.max_bytes:
            with self._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                tick=db.execute('SELECT coalesce(max(touched),0)+1 FROM entries').fetchone()[0]
                db.execute('INSERT OR REPLACE INTO entries VALUES (?,?,0,?)',(key,payload,tick))
                self._trim(db)
        returned=json.loads(payload)
        returned['usage']=dict(returned['usage'],cache_hit=False,persistent_hit=False,extractor_revision=revision)
        return returned

    def clear(self):
        with self._connection() as db:db.execute('DELETE FROM entries')

    def stats(self):
        with self._connection() as db:
            count,size=db.execute('SELECT count(*),coalesce(sum(length(payload)+length(key)),0) FROM entries').fetchone()
        with self._lock:
            return dict(entries=count,serialized_bytes=size,hits=self.hits,misses=self.misses,evictions=self.evictions,
                        byte_scope='serialized payload and key bytes; not database file or RAM',
                        counters_scope='current process')
