"""Versioned local admission membrane, not a global resource reservation."""
import hashlib
import re
from .controller import Fault
from .reservoir import RetirementReservoir

_TABLE='''CREATE TABLE ocn_reserved (
    id INTEGER PRIMARY KEY CHECK(id=1),
    format INTEGER NOT NULL CHECK(format=1),
    capacity INTEGER NOT NULL CHECK(capacity>=1),
    reserve INTEGER NOT NULL CHECK(reserve>=0 AND reserve<capacity),
    load INTEGER NOT NULL CHECK(load>=0 AND load<=capacity-reserve),
    stream TEXT, sequence INTEGER NOT NULL CHECK(sequence>=0), digest TEXT
)'''
_VIEW='''CREATE VIEW state AS SELECT id,capacity,load,stream,sequence,digest FROM ocn_reserved'''
_TRIGGER='''CREATE TRIGGER ocn_reserved_contract_immutable
BEFORE UPDATE OF format,capacity,reserve ON ocn_reserved
BEGIN SELECT RAISE(ABORT,'immutable admission contract'); END'''
_SCHEMA={'ocn_reserved':('table',_TABLE),'state':('view',_VIEW),
         'ocn_reserved_contract_immutable':('trigger',_TRIGGER)}


class ReservedCompactReservoir(RetirementReservoir):
    """A separate storage format. Legacy reservoirs cannot write through its view.

    All writers and the SQLite host remain trusted; this is not tamper resistance.
    No implicit migration of legacy databases is performed.
    """
    def __init__(self,path,capacity=16,reserve=1):
        if type(capacity) is not int or capacity<1 or type(reserve) is not int or not 0<=reserve<capacity:
            raise ValueError('Invalid capacity or reserve')
        self.path=str(path);self._configuration=(1,capacity,reserve)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing={name:(kind,sql) for name,kind,sql in db.execute(
                "SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
            if not existing:
                for statement in (_TABLE,_VIEW,_TRIGGER):db.execute(statement)
                db.execute('INSERT INTO ocn_reserved VALUES (1,1,?,?,0,NULL,0,NULL)',(capacity,reserve))
            elif existing!=_SCHEMA:
                raise ValueError('Unsupported reservoir storage format; no implicit migration')
            self._row(db)

    def _row(self,db):
        rows=db.execute('SELECT format,capacity,reserve,load,stream,sequence,digest FROM ocn_reserved').fetchall()
        if len(rows)!=1 or tuple(rows[0][:3])!=self._configuration:
            raise ValueError('Admission contract mismatch')
        return rows[0]

    def descriptor(self):
        with self.connect() as db:
            _,capacity,reserve,*_=self._row(db)
        return dict(format='ocn.local-reserved.v1',capacity=capacity,reserve=reserve,
                    scope='single_stream_local_admission')

    def accept(self,stream,event):
        if type(stream) is not str or not re.fullmatch('[0-9a-f]{32}',stream):raise Fault('invalid_stream')
        if (type(event) is not dict or set(event)!={'sequence','digest','count','sealed'}
                or type(event['sequence']) is not int or event['sequence']<1
                or type(event['count']) is not int or event['count']<1 or event['sealed'] is not True
                or type(event['digest']) is not str or not re.fullmatch('[0-9a-f]{64}',event['digest'])):
            raise Fault('invalid_compact_emission')
        digest=hashlib.sha256((str(event['count'])+':'+event['digest']).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _,capacity,reserve,load,owner,last,previous=self._row(db)
            if owner is not None and owner!=stream:raise Fault('stream_mismatch')
            sequence=event['sequence']
            if sequence<=last:
                if sequence==last and digest!=previous:raise Fault('sequence_conflict')
                return dict(accepted=True,pressure=load/capacity)
            if sequence!=last+1:raise Fault('sequence_gap')
            if load+1>capacity-reserve:return dict(accepted=False,pressure=load/capacity)
            db.execute('UPDATE ocn_reserved SET load=?,stream=?,sequence=?,digest=? WHERE id=1',
                       (load+1,stream,sequence,digest))
            return dict(accepted=True,pressure=(load+1)/capacity)

    def drain(self,units):
        if type(units) is not int or units<0:raise ValueError('Invalid drain')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._row(db)
            db.execute('UPDATE ocn_reserved SET load=max(0,load-?) WHERE id=1',(units,))

    def status(self):
        with self.connect() as db:
            _,capacity,reserve,load,_,sequence,_=self._row(db)
        return dict(capacity=capacity,reserve=reserve,load=load,sequence=sequence)
