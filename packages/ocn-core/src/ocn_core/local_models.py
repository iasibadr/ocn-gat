"""Read-only catalogue of already installed loopback Ollama models."""
import json
import urllib.request


def installed_models():
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:
        raise ValueError('Local model catalogue too large')
    data=json.loads(raw)
    if type(data) is not dict or type(data.get('models')) is not list:
        raise ValueError('Invalid local model catalogue')
    result=[];seen=set()
    for entry in data['models']:
        if (type(entry) is not dict or type(entry.get('name')) is not str or not entry['name'].strip()
            or type(entry.get('digest')) is not str or not entry['digest'].strip()
            or type(entry.get('size')) is not int or entry['size']<0 or entry['name'] in seen):
            raise ValueError('Invalid or duplicate installed model')
        seen.add(entry['name'])
        result.append(dict(name=entry['name'],digest=entry['digest'],size_bytes=entry['size']))
    return sorted(result,key=lambda entry:entry['name'])


def require_model(name):
    for entry in installed_models():
        if entry['name']==name:return entry
    raise ValueError('Local model is not installed: '+name+'; use ocn-local models to list exact identifiers')
