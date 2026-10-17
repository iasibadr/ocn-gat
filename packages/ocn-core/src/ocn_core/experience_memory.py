"""Bounded persistent host-observed outcomes, separate from their valuation.

Experimental trusted-host library, not authenticated evidence or a GAT daemon.
"""
import json
import hashlib
import os
from pathlib import Path
import sqlite3
from contextlib import closing,contextmanager
from .reward_selection import finite


def label(value):
    if type(value) is not str or not value.strip() or len(value.encode())>256:
        raise ValueError('Nonempty label of at most 256 bytes required')
    return value


class ExperienceMemory:
    @classmethod
    def create(cls,path,*,contract_id,actions,capacity=2048):
        label(contract_id)
        if type(actions) not in (list,tuple) or not 1<=len(actions)<=64:raise ValueError('Bounded action catalogue required')
        for a in actions:label(a)
        if len(set(actions))!=len(actions):raise ValueError('Duplicate actions')
        if type(capacity) is not int or not 1<=capacity<=100000:raise ValueError('Invalid capacity')
        path=Path(path).absolute()
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        # On failure keep the incomplete file for diagnosis; never silently recreate.
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            db.execute('CREATE TABLE outcomes (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, context TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX by_context_action ON outcomes(context,action,seq)')
            meta=dict(format='gat.experience.v1',contract_id=contract_id,actions=list(actions),capacity=capacity)
            db.execute('INSERT INTO metadata VALUES (1,?)',(json.dumps(meta),))
            db.commit()
        return cls(path,contract_id=contract_id)

    def __init__(self,path,*,contract_id):
        label(contract_id);self.path=Path(path).absolute();self.contract_id=contract_id
        with self.connect() as db:self.metadata(db)

    @contextmanager
    def connect(self):
        if self.path.is_symlink():raise ValueError('Memory symlinks forbidden')
        db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=1.)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:yield db
        finally:db.close()

    def metadata(self,db):
        rows=db.execute('SELECT payload FROM metadata WHERE id=1').fetchall()
        if len(rows)!=1:raise ValueError('Missing memory metadata')
        meta=json.loads(rows[0][0])
        if meta.get('format') not in ('gat.experience.v1','gat.experience.v2') or meta.get('contract_id')!=self.contract_id:
            raise ValueError('Experience contract mismatch')
        return meta

    def record(self,*,event_id,context,action,success,quality,interventions,cost,environment=None):
        for v in (event_id,context,action):label(v)
        if type(success) is not bool:raise ValueError('Boolean success required')
        finite(quality,'quality')
        if cost is not None:finite(cost,'cost')
        if not 0<=quality<=1 or (cost is not None and cost<0):raise ValueError('Invalid observed quality or cost')
        if type(interventions) is not int or not 0<=interventions<=1000000:raise ValueError('Invalid intervention count')
        fact=dict(success=success,quality=float(quality),interventions=interventions,
                  cost=None if cost is None else float(cost))
        if environment is not None:
            if type(environment) is not dict or set(environment)!={'route_attempts','route_failures','preference_switches'}:
                raise ValueError('Exact route-environment observation required')
            if any(type(v) is not int or not 0<=v<=1000000 for v in environment.values()):
                raise ValueError('Invalid route-environment counts')
            if environment['route_failures']>environment['route_attempts']:
                raise ValueError('Route failures exceed attempts')
            fact['environment']=dict(environment)
        payload=json.dumps(fact,sort_keys=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');meta=self.metadata(db)
            if action not in meta['actions']:raise ValueError('Unknown action')
            old=db.execute('SELECT context,action,payload FROM outcomes WHERE event_id=?',(event_id,)).fetchone()
            if old is not None:
                if old!=(context,action,payload):raise ValueError('Conflicting event replay')
                return False
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retired'").fetchone():
                retired=db.execute('SELECT fingerprint FROM retired WHERE event_id=?',(event_id,)).fetchone()
                if retired is not None:
                    if retired[0]!=self.fingerprint(context,action,payload):raise ValueError('Conflicting retired event replay')
                    return False
            if db.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0]>=meta['capacity']:
                raise ValueError('Experience capacity exhausted; no implicit deletion')
            db.execute('INSERT INTO outcomes(event_id,context,action,payload) VALUES (?,?,?,?)',(event_id,context,action,payload))
        return True

    @staticmethod
    def fingerprint(context,action,payload):
        return hashlib.sha256(json.dumps([context,action,payload],ensure_ascii=False).encode()).hexdigest()

    def retire(self,reservoir,*,keep_per_pair=32,limit=256):
        """Archive older per-context/action outcomes before transactional retirement.

        Latest keep_per_pair outcomes remain active; forecasts with larger windows
        are subsequently refused. Archive capacity and replay markers are bounded.
        Caller chooses an external trusted reservoir; no automatic background run.
        """
        if type(keep_per_pair) is not int or not 32<=keep_per_pair<=256:raise ValueError('Retention window must be 32..256')
        if type(limit) is not int or not 1<=limit<=256:raise ValueError('Retirement batch must be 1..256')
        reservoir=Path(reservoir).absolute()
        if reservoir.is_symlink() or not reservoir.is_dir():raise ValueError('Existing non-symlink reservoir required')
        from .model_budget import sync_directory
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');meta=self.metadata(db)
            if keep_per_pair>meta.get('max_window',256):raise ValueError('Cannot expand a retired prediction window')
            db.execute('CREATE TABLE IF NOT EXISTS retired (event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, archive TEXT NOT NULL)')
            count=db.execute('SELECT COUNT(*) FROM retired').fetchone()[0]
            rows=db.execute('''SELECT seq,event_id,context,action,payload FROM
                (SELECT *,ROW_NUMBER() OVER (PARTITION BY context,action ORDER BY seq DESC) AS rank FROM outcomes)
                WHERE rank>? ORDER BY seq LIMIT ?''',(keep_per_pair,limit)).fetchall()
            if not rows:return dict(retired=0,archive=None)
            if count+len(rows)>4*meta['capacity']:raise ValueError('Retired replay-marker capacity exhausted')
            raw=json.dumps(dict(format='gat.experience-archive.v1',contract_id=self.contract_id,
                                rows=rows),sort_keys=True,ensure_ascii=False).encode()
            if len(raw)>1048576:raise ValueError('Archive batch too large')
            sha=hashlib.sha256(raw).hexdigest();path=reservoir/(sha+'.json')
            from .archive_publication import publish
            publish(path,raw)
            with path.open('rb') as f:
                verified=f.read(len(raw)+1)
                os.fsync(f.fileno())
            if verified!=raw:raise ValueError('Archive verification failed')
            sync_directory(reservoir)
            for seq,event,context,action,payload in rows:
                db.execute('INSERT INTO retired VALUES (?,?,?)',(event,self.fingerprint(context,action,payload),str(path)))
                db.execute('DELETE FROM outcomes WHERE seq=?',(seq,))
            meta['max_window']=keep_per_pair
            meta['format']='gat.experience.v2'  # Older writers must not bypass retired-event markers.
            db.execute('UPDATE metadata SET payload=? WHERE id=1',(json.dumps(meta),))
        return dict(retired=len(rows),archive=str(path),sha256=sha,retained_window=keep_per_pair)

    def estimate(self,context,action,*,success_weight=1.,quality_weight=0.,intervention_penalty=0.,window=32,rate=.25):
        label(context);label(action)
        for v in (success_weight,quality_weight,intervention_penalty):
            finite(v,'valuation weight')
            if v<0:raise ValueError('Nonnegative weights required')
        finite(rate,'rate')
        if not 0<rate<=1 or type(window) is not int or not 1<=window<=256:raise ValueError('Invalid learning window or rate')
        with self.connect() as db:
            meta=self.metadata(db)
            if window>meta.get('max_window',256):raise ValueError('Prediction window exceeds retained history')
            if action not in meta['actions']:raise ValueError('Unknown action')
            rows=db.execute('SELECT payload FROM outcomes WHERE context=? AND action=? ORDER BY seq DESC LIMIT ?',
                            (context,action,window)).fetchall()
        if not rows:return dict(expected_return=None,observations=0,uncertainty='unknown')
        values=[]
        for row in reversed(rows):
            fact=json.loads(row[0])
            value=success_weight*int(fact['success'])+quality_weight*fact['quality']-intervention_penalty*fact['interventions']
            values.append(finite(value,'evaluated outcome'))
        estimate=values[0]
        for value in values[1:]:estimate=(1-rate)*estimate+rate*value
        return dict(expected_return=finite(estimate,'estimate'),observations=len(values),
                    uncertainty='uncalibrated',observed_range=[min(values),max(values)])
