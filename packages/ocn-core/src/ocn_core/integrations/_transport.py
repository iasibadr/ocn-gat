"""Flat typed transport translated into framework calls, no text execution."""
import json
ARGUMENTS={'read':('source','path'),'locate':('source',),'describe':('source',),'final_answer':('answer',),'evaluate':(),'abstain':()}

def schema(names):
    if not names or any(n not in ARGUMENTS for n in names):raise ValueError('Unknown tool set')
    return dict(type='object',properties=dict(name=dict(type='string',enum=list(names)),
        source=dict(type='string'),path=dict(type='string'),answer=dict(type='integer')),
        required=['name','source','path','answer'],additionalProperties=False)

def parse(content,names):
    content=content.strip()
    if content.startswith('Action:'):content=content[len('Action:'):].lstrip()
    value=json.loads(content)
    if type(value) is not dict or set(value)!={'name','source','path','answer'}:raise ValueError('Invalid call')
    if any(type(value[k]) is not str for k in ('name','source','path')) or type(value['answer']) is not int:
        raise ValueError('Invalid argument type')
    name=value['name']
    if name not in names or name not in ARGUMENTS:raise ValueError('Unknown tool')
    for key in ('source','path','answer'):
        if name=='evaluate' and key=='answer':continue  # Not passed to the tool.
        if key not in ARGUMENTS[name] and value[key] != (0 if key=='answer' else ''):
            raise ValueError('Unused fields must be empty or zero')
    return dict(name=name,arguments={key:value[key] for key in ARGUMENTS[name]})
