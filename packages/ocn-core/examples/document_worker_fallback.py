"""Offline demonstration of bounded worker fallback; no LLM or network.

The primary fixture intentionally returns an invalid quotation. The secondary
fixture supplies an exact quote. This verifies plumbing, not model intelligence.
Run after installing ocn-core: python document_worker_fallback.py
"""
import hashlib
import json
import tempfile
from pathlib import Path
from ocn_core.document_adapter import DocumentAdapter
from ocn_core.document_session import DocumentSession


def main():
    def secondary(question,fields,identity,text):
        return dict(observations=[dict(source_id=identity,field='city',
            sha256=hashlib.sha256(text.encode()).hexdigest(),status='value',
            value='Taza',quote='City Taza.')],usage=dict(model_calls=1,input_tokens=8,output_tokens=4))
    def primary(*args):
        result=secondary(*args)
        result['observations'][0]['quote']='Invented quotation'
        return result
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);habitat=root/'documents';habitat.mkdir()
        source=habitat/'city.txt';source.write_text('City Taza.')
        adapter=DocumentAdapter(habitat,root/'bindings.json');adapter.bind('city','city.txt')
        session=DocumentSession({'local':adapter},primary,lambda:'primary-fixture-v1',
            fallback_worker=secondary,fallback_revision=lambda:'secondary-fixture-v1',
            max_model_calls=2,max_requests=4)
        def answer(question='Which city?'):
            return session.answer(question,{'city':'Copy city name.'},('city',))
        first=answer()
        assert first['values']=={'city':'Taza'} and first['session']['model_calls']==2
        assert first['reported_usage'][0]['input_tokens']==16
        print(json.dumps(dict(stage='fallback',values=first['values'],attempts=session.attempts(),fixture=True)))
        source.rename(habitat/'relocated.txt')
        moved=answer()
        assert moved['session']['model_calls']==0 and moved['source_paths']['city']=='local/relocated.txt'
        print(json.dumps(dict(stage='moved',path=moved['source_paths']['city'],new_worker_calls=0,fixture=True)))
        try:answer('Name the city again using a new question')
        except RuntimeError as exc:
            assert 'budget' in str(exc);print(json.dumps(dict(stage='budget',refused=True,total_calls=session.calls)))
        else:raise AssertionError('Budget bypassed')
        (habitat/'relocated.txt').write_text('City Rabat.')
        try:answer()
        except ValueError:
            print(json.dumps(dict(stage='changed_source',refused=True,total_calls=session.calls)))
        else:raise AssertionError('Changed source accepted')

if __name__=='__main__':main()
