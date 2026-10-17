"""Durable bounded sink for one linear agent stream, not a physical environment."""
from contextlib import contextmanager
import re
import sqlite3
from .habitat import DirectoryHabitat
from .controller import Fault

class RetirementReservoir:
    supports_atomic_refusal = True

    def __init__(self,path,capacity=16):
        if type(capacity) is not int or capacity<1:raise ValueError('Invalid reservoir capacity')
        self.path=str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), capacity INTEGER, load INTEGER, stream TEXT, sequence INTEGER, digest TEXT)')
            db.execute('INSERT OR IGNORE INTO state VALUES (1,?,0,NULL,0,NULL)',(capacity,))
            if db.execute('SELECT capacity FROM state WHERE id=1').fetchone()[0]!=capacity:
                raise ValueError('Reservoir capacity mismatch')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:yield db
        finally:db.close()

    def accept(self,stream,event):
        if type(stream) is not str or not re.fullmatch('[0-9a-f]{32}',stream):raise Fault('invalid_stream')
        if type(event) is not dict or set(event)!= {'sequence','digest'} or type(event['sequence']) is not int or event['sequence']<1 or type(event['digest']) is not str or not re.fullmatch('[0-9a-f]{64}',event['digest']):raise Fault('invalid_emission')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            capacity,load,owner,last,digest=db.execute('SELECT capacity,load,stream,sequence,digest FROM state WHERE id=1').fetchone()
            if owner is not None and owner!=stream:raise Fault('stream_mismatch')
            seq=event['sequence']
            if seq<=last:
                if seq==last and event['digest']!=digest:raise Fault('sequence_conflict')
                return dict(accepted=True,pressure=load/capacity)
            if seq!=last+1:raise Fault('sequence_gap')
            if load>=capacity:return dict(accepted=False,pressure=1.)
            db.execute('UPDATE state SET load=?,stream=?,sequence=?,digest=? WHERE id=1',(load+1,stream,seq,event['digest']))
            return dict(accepted=True,pressure=(load+1)/capacity)

    def drain(self,units):
        """External operator/consumer processes units; never called by the agent."""
        if type(units) is not int or units<0:raise ValueError('Invalid drain')
        with self.connect() as db:
            db.execute('UPDATE state SET load=max(0,load-?) WHERE id=1',(units,))

    def status(self):
        with self.connect() as db:
            capacity,load,sequence=db.execute('SELECT capacity,load,sequence FROM state WHERE id=1').fetchone()
        return dict(capacity=capacity,load=load,sequence=sequence)

class DissipativeHabitat(DirectoryHabitat):
    @property
    def admission_descriptor(self):
        describe=getattr(self.reservoir,'descriptor',None)
        return describe() if callable(describe) else None

    @property
    def supports_atomic_refusal(self):
        return getattr(self.reservoir, 'supports_atomic_refusal', False) is True

    def __init__(self,root,dna,reservoir,**kwargs):
        super().__init__(root,dna,**kwargs)
        from pathlib import Path
        location=Path(reservoir.path).resolve()
        if location==self.root or self.root in location.parents:
            raise ValueError('Reservoir must be outside readable habitat')
        self.reservoir=reservoir

    def dissipate(self,stream,event):
        self.charge('dissipate',event['sequence'])
        try:return self.reservoir.accept(stream,event)
        except sqlite3.Error:raise Fault('reservoir_unavailable') from None
