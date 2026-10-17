"""Bounded JSON envelope repair anchored to host-pinned document content.

Only nested object/list wrappers around unchanged UTF-8 text are recoverable.
No source version upgrade, new endpoint discovery or execution of source code.
Shape/path memory saves hash candidates, not traversal or transport bytes.
"""
from collections import OrderedDict
import hashlib
import http.client
import json
import re
from urllib.parse import quote
from .document_adapter import Document, DocumentAdapter


class EnvelopeDocuments(DocumentAdapter):
    def __init__(self, port, pins, *, remember=True):
        if type(port) is not int or not 1<=port<=65535:raise ValueError('Loopback port required')
        if type(pins) is not dict or not 1<=len(pins)<=8:raise ValueError('One to eight host pins required')
        for identity,digest in pins.items():
            if type(identity) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,64}',identity) is None:
                raise ValueError('Bounded host identity required')
            if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}',digest) is None:raise ValueError('SHA256 required')
        if type(remember) is not bool:raise ValueError('Boolean memory option required')
        self.port=port;self.pins=dict(pins);self.remember=remember
        self.methods=OrderedDict();self.hash_checks=0;self.acquisitions=0;self.reuses=0
    def bindings(self):return {k:dict(sha256=v) for k,v in self.pins.items()}
    def bind(self,*a,**kw):raise ValueError('Host pins immutable')
    def accept_version(self,*a,**kw):raise ValueError('Host pins immutable')
    def decode(self, raw, identity):
        if identity not in self.pins:raise ValueError('Unknown identity')
        if type(raw) is not bytes or len(raw)>524288:raise ValueError('Envelope byte budget')
        def unique(pairs):
            result=dict(pairs)
            if len(result)!=len(pairs):raise ValueError('Duplicate JSON fields')
            return result
        def nonfinite(_):raise ValueError('Nonfinite JSON number')
        try:data=json.loads(raw,object_pairs_hook=unique,parse_constant=nonfinite)
        except (RecursionError,UnicodeError) as exc:raise ValueError('Invalid envelope') from exc
        leaves=[];shape=[];nodes=0
        def walk(value,path=()):
            nonlocal nodes
            nodes+=1
            if nodes>256 or len(path)>8:raise ValueError('Envelope structure budget')
            shape.append((path,type(value).__name__))
            if type(value) is dict:
                for key in sorted(value):
                    if len(key.encode())>128:raise ValueError('Envelope key budget')
                    walk(value[key],path+(key,))
            elif type(value) is list:
                for i,item in enumerate(value):walk(item,path+(i,))
            elif type(value) is str:
                if len(value.encode())>65536:raise ValueError('Leaf byte budget')
                leaves.append((path,value))
        walk(data)
        signature=hashlib.sha256(json.dumps(shape).encode()).hexdigest()
        def matches(text):
            self.hash_checks+=1
            return hashlib.sha256(text.encode()).hexdigest()==self.pins[identity]
        known=self.methods.get(signature) if self.remember else None
        values=dict(leaves);text=None;path=None
        if known in values and matches(values[known]):
            text=values[known];path=known
            # Reuse never bypasses duplicate detection or content verification.
            if sum(v==text for _,v in leaves)!=1:raise ValueError('Ambiguous content copies')
            self.reuses+=1
        else:
            candidates=[(p,v) for p,v in leaves if matches(v)]
            if len(candidates)!=1:raise ValueError('Expected one pinned content occurrence')
            path,text=candidates[0];self.acquisitions+=1
        if self.remember:
            self.methods.pop(signature,None);self.methods[signature]=path
            while len(self.methods)>8:self.methods.popitem(last=False)
        return text,dict(path=list(path),nodes=nodes,shape_sha256=signature)
    def validate_reference(self, document, quote):
        if type(document) is not Document or document.document_id not in self.pins:
            raise ValueError('Authorized document snapshot required')
        if (document.sha256!=self.pins[document.document_id] or
            hashlib.sha256(document.text.encode()).hexdigest()!=document.sha256):
            raise ValueError('Snapshot version mismatch')
        if type(quote) is not str or not quote.strip():raise ValueError('Nonempty quote required')
        fresh=self.read(document.document_id)
        if quote not in fresh.text:raise ValueError('Quote absent from fresh source')
        return dict(document_id=fresh.document_id,path=fresh.path,sha256=fresh.sha256,
            quote_sha256=hashlib.sha256(quote.encode()).hexdigest(),bytes_read=fresh.bytes_read)

    def read(self, document_id, *, discovery_bytes=None):
        if document_id not in self.pins:raise ValueError('Unknown identity')
        if discovery_bytes is not None and (type(discovery_bytes) is not int or discovery_bytes<0):raise ValueError('Invalid discovery hint')
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        path='/document/'+quote(document_id,safe='')
        try:
            conn.request('GET',path);response=conn.getresponse();raw=response.read(524289)
            if response.status!=200:raise ValueError('Document service rejected request')
            text,evidence=self.decode(raw,document_id)
            # Provenance is the actually accessed endpoint, not a guessed path
            # from the changed server envelope. Counters describe this decoder.
            return Document(document_id,f'http://127.0.0.1:{self.port}'+path,
                self.pins[document_id],text,None,len(raw),evidence['nodes'])
        finally:conn.close()
