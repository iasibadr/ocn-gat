"""Parse model JSON with explicit, auditable framing tolerance, never field repair."""
from dataclasses import dataclass
import hashlib
import json
import math


@dataclass(frozen=True)
class ParsedJSON:
    value: dict
    framing: str
    raw_sha256: str
    payload_sha256: str


def parse_model_json(text,*,allow_json_fence=False,max_bytes=65536):
    if type(allow_json_fence) is not bool:raise ValueError('Boolean framing permission required')
    if type(max_bytes) is not int or not 1<=max_bytes<=2*1024*1024:raise ValueError('Invalid JSON byte budget')
    if type(text) is not str:raise ValueError('Model JSON text required')
    raw=text.encode('utf-8')
    if len(raw)>max_bytes:raise ValueError('Model JSON exceeds byte budget')
    payload=text.strip(' \t\r\n');framing='plain_json'
    if allow_json_fence and payload.startswith('```json\n') and payload.endswith('\n```'):
        payload=payload[len('```json\n'):-len('\n```')];framing='single_json_fence'
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    def constant(_):raise ValueError('Nonfinite JSON constant')
    def floating(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('Nonfinite JSON number')
        return result
    try:
        value=json.loads(payload,object_pairs_hook=pairs,parse_constant=constant,parse_float=floating)
    except RecursionError as exc:raise ValueError('JSON nesting exceeds parser capacity') from exc
    if type(value) is not dict:raise ValueError('Model JSON must be an object')
    pending=[(value,1)]
    while pending:
        item,depth=pending.pop()
        if depth>32:raise ValueError('Model JSON nesting exceeds 32 levels')
        if type(item) is dict:pending.extend((v,depth+1) for v in item.values() if type(v) in (dict,list))
        elif type(item) is list:pending.extend((v,depth+1) for v in item if type(v) in (dict,list))
    return ParsedJSON(value,framing,hashlib.sha256(raw).hexdigest(),hashlib.sha256(payload.encode()).hexdigest())
