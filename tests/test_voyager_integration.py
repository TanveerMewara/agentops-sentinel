import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from examples.voyager_ai_agent import VoyagerClient,monitored_execution,sanitized_result,validate_endpoint

class Handler(BaseHTTPRequestHandler):
    seen_authorization=None
    def do_POST(self):
        Handler.seen_authorization=self.headers.get("Authorization")
        length=int(self.headers.get("Content-Length","0"));self.rfile.read(length)
        if self.path=="/stream":
            body=(json.dumps({"type":"text","text":"partial"})+"\n"+json.dumps({"type":"done","text":"private plan","first_text_seconds":0.12,"generation_seconds":0.45})+"\n").encode()
            content_type="application/x-ndjson"
        else:
            body=json.dumps({"status":"success","itineraries":[{"private":"excluded"}]}).encode();content_type="application/json"
        self.send_response(200);self.send_header("Content-Type",content_type);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass

class FakeClient:
    def __init__(self):self.run_id="run-1"
    def create_run(self,*args):return {"run_id":self.run_id}
    def submit_external_trace(self,run_id,evidence):self.evidence=evidence;return {"trace_id":"trace-1"}
    def complete_run(self,run_id):return {"run_id":run_id,"status":"succeeded"}

class VoyagerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),Handler);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def test_external_http_requires_https(self):
        with self.assertRaisesRegex(ValueError,"HTTPS"):validate_endpoint("http://example.com/plan")
    def test_response_is_reduced_to_safe_metadata(self):
        result=sanitized_result({"status":"success","itineraries":[{"passport":"secret"}]},120)
        self.assertEqual(result["recommendation_count"],1);self.assertNotIn("passport",str(result));self.assertIn("response_sha256",result)
    def test_voyager_ndjson_stream_is_reduced_to_timing_and_hash(self):
        voyager=VoyagerClient(f"http://127.0.0.1:{self.server.server_port}/stream")
        response,_,size=voyager.invoke({"synthetic":True});safe=sanitized_result(response,size)
        self.assertEqual(safe["reported_result"],"success");self.assertEqual(safe["voyager_first_text_seconds"],0.12);self.assertEqual(safe["voyager_generation_seconds"],0.45);self.assertNotIn("private plan",json.dumps(safe))
    def test_http_and_sentinel_trace_exclude_payload_and_secret(self):
        voyager=VoyagerClient(f"http://127.0.0.1:{self.server.server_port}/plan",api_key="voyager-secret")
        developer=FakeClient();worker=FakeClient();payload={"traveler":"private-name","destination":"Jaipur"}
        result=monitored_execution(developer,worker,voyager,{"agent_version_id":"version-1"},payload,"stable-key")
        self.assertEqual(result["status"],"succeeded");self.assertEqual(Handler.seen_authorization,"Bearer voyager-secret")
        serialized=json.dumps(worker.evidence);self.assertNotIn("private-name",serialized);self.assertNotIn("Jaipur",serialized);self.assertNotIn("voyager-secret",serialized)
if __name__=="__main__":unittest.main()
