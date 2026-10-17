import hashlib,json,threading,unittest
from http.server import HTTPServer,BaseHTTPRequestHandler
from ocn_core.envelope_documents import EnvelopeDocuments
from ocn_core.evidence_agent import EvidenceAgent
from ocn_core.extraction_cache import ExtractionCache

class Tests(unittest.TestCase):
    def test_http_schema_changes_reach_worker_with_immutable_content(self):
        text='City Taza.';digest=hashlib.sha256(text.encode()).hexdigest()
        body={'text':text,'meta':'fixture'}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                raw=json.dumps(body).encode();self.send_response(200);self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        self.addCleanup(thread.join);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        calls=[]
        def worker(question,fields,identity,source):
            calls.append(identity)
            return dict(observations=[dict(field='city',source_id=identity,sha256=digest,status='value',value='Taza',quote=source)],usage={'model_calls':1})
        adapters=[EnvelopeDocuments(server.server_port,{'D':digest},remember=r) for r in (True,False)]
        agents=[EvidenceAgent(a,ExtractionCache(worker,lambda:'fixture')) for a in adapters]
        def answer(agent):return agent.answer('Which city?',{'city':'City'},('D',))
        for stage in ({'text':text,'meta':'fixture'}, {'wrapper':{'body':[text]},'note':'changed'},
                      {'wrapper':{'body':[text]},'note':'changed'}):
            body.clear();body.update(stage)
            for agent in agents:self.assertEqual(answer(agent)['values'],{'city':'Taza'})
        self.assertEqual(calls,['D','D']) # Per-agent extraction reuse, fresh network reads.
        self.assertLess(adapters[0].hash_checks,adapters[1].hash_checks)
        snapshot=adapters[0].read('D')
        verified=adapters[0].validate_reference(snapshot,'City Taza.')
        self.assertEqual(verified['sha256'],digest)
        from dataclasses import replace
        with self.assertRaises(ValueError):adapters[0].validate_reference(replace(snapshot,text='forged'),'City Taza.')
        body.clear();body.update({'wrapper':{'body':['City Rabat.']},'note':'changed'})
        with self.assertRaises(ValueError):adapters[0].validate_reference(snapshot,'City Taza.')
        for agent in agents:
            with self.assertRaises(ValueError):answer(agent)
        self.assertEqual(calls,['D','D'])

if __name__=='__main__':unittest.main()
