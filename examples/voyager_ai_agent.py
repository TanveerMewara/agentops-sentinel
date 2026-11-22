"""Privacy-minimal JSON/HTTP adapter for connecting Voyager AI to Sentinel."""
from __future__ import annotations
import argparse,hashlib,json,os
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler,ProxyHandler,Request,build_opener
from sentinel.client import SentinelClient
from sentinel.trace_recorder import TraceRecorder

MAX_RESPONSE_BYTES=256*1024
SAFE_STATUS={"ok","success","succeeded","completed","failed","error"}

class VoyagerError(RuntimeError):
    def __init__(self,status):
        self.status=status;super().__init__(f"Voyager request failed (HTTP {status}).")
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):return None

def validate_endpoint(value):
    parsed=urlsplit(value);loopback=parsed.hostname in ("localhost","127.0.0.1","::1")
    if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Use an HTTP(S) Voyager URL without embedded credentials or fragments.")
    if parsed.scheme=="http" and not loopback:raise ValueError("Voyager must use HTTPS outside localhost.")
    return value

def request_fingerprint(payload):
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(canonical).hexdigest()

def sanitized_result(payload,encoded_size):
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    result={"response_sha256":hashlib.sha256(canonical).hexdigest(),"response_bytes":encoded_size,"top_level_key_count":len(payload)}
    for key in ("itineraries","trips","options","recommendations"):
        if isinstance(payload.get(key),list):result["recommendation_count"]=len(payload[key]);break
    status=payload.get("status")
    if isinstance(status,str) and status.lower() in SAFE_STATUS:result["reported_result"]=status.lower()
    for source,target in (("first_text_seconds","voyager_first_text_seconds"),("generation_seconds","voyager_generation_seconds")):
        value=payload.get(source)
        if isinstance(value,(int,float)) and not isinstance(value,bool) and 0<=value<=300:result[target]=round(float(value),3)
    return result

class VoyagerClient:
    def __init__(self,endpoint,*,api_key=None,auth_header="Authorization",auth_scheme="Bearer",timeout=30.0):
        self.endpoint=validate_endpoint(endpoint)
        if timeout<=0 or timeout>300:raise ValueError("Voyager timeout must be between 0 and 300 seconds.")
        if not auth_header or any(char in auth_header for char in "\r\n:"):raise ValueError("Voyager authentication header is invalid.")
        self.api_key=api_key;self.auth_header=auth_header;self.auth_scheme=auth_scheme.strip();self.timeout=timeout
        self.opener=build_opener(ProxyHandler({}),NoRedirect())
    def invoke(self,payload):
        body=json.dumps(payload,separators=(",",":")).encode();headers={"Content-Type":"application/json","Accept":"application/json, application/x-ndjson"}
        if self.api_key:headers[self.auth_header]=f"{self.auth_scheme} {self.api_key}" if self.auth_scheme else self.api_key
        request=Request(self.endpoint,data=body,headers=headers,method="POST");started=perf_counter()
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                content_type=response.headers.get_content_type();raw=response.read(MAX_RESPONSE_BYTES+1);status=response.status
        except HTTPError as error:
            status=error.code;error.close();raise VoyagerError(status) from None
        except (URLError,TimeoutError,OSError):raise VoyagerError(0) from None
        elapsed_ms=(perf_counter()-started)*1000
        if status<200 or status>=300:raise VoyagerError(status)
        if content_type not in ("application/json","application/x-ndjson") or len(raw)>MAX_RESPONSE_BYTES:raise VoyagerError(502)
        try:
            if content_type=="application/json":decoded=json.loads(raw)
            else:
                events=[json.loads(line) for line in raw.decode().splitlines() if line.strip()]
                if any(event.get("type")=="error" for event in events):raise VoyagerError(502)
                done=next((event for event in reversed(events) if event.get("type")=="done"),None)
                if not done or not isinstance(done.get("text"),str) or not done["text"].strip():raise VoyagerError(502)
                decoded={"status":"success","plan":done["text"],"first_text_seconds":done.get("first_text_seconds"),"generation_seconds":done.get("generation_seconds")}
        except (UnicodeDecodeError,json.JSONDecodeError):raise VoyagerError(502) from None
        if not isinstance(decoded,dict):raise VoyagerError(502)
        return decoded,elapsed_ms,len(raw)

def register_voyager(developer,version):
    agent=developer.register_agent("voyager_ai","Voyager AI","External travel-planning agent monitored by Sentinel.")
    return developer.create_version(agent["agent_id"],version,"External travel agent. Request and response content stay outside Sentinel.")

def monitored_execution(developer,worker,voyager,version,payload,idempotency_key):
    started=perf_counter();run=developer.create_run(version["agent_version_id"],idempotency_key,{"workflow":"external_voyager_ai","request_sha256":request_fingerprint(payload)})
    create_ms=(perf_counter()-started)*1000;recorder=TraceRecorder(source="voyager_ai_http")
    with recorder.span("agent.run"):
        with recorder.span("voyager.plan_trip","tool"):
            response,voyager_ms,response_bytes=voyager.invoke(payload)
    safe_output=sanitized_result(response,response_bytes)
    evidence=recorder.finish(safe_output,reported_status="succeeded",idempotency_key="voyager-trace-"+hashlib.sha256(idempotency_key.encode()).hexdigest())
    started=perf_counter();trace=worker.submit_external_trace(run["run_id"],evidence);submit_ms=(perf_counter()-started)*1000
    started=perf_counter();completed=worker.complete_run(run["run_id"]);complete_ms=(perf_counter()-started)*1000
    return {"run_id":completed["run_id"],"trace_id":trace["trace_id"],"status":completed["status"],"voyager_ms":round(voyager_ms,6),"sentinel_create_ms":round(create_ms,6),"sentinel_submit_ms":round(submit_ms,6),"sentinel_complete_ms":round(complete_ms,6),"safe_output":safe_output}

def load_object(path):
    value=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value,dict):raise ValueError("Voyager request JSON must be an object.")
    return value

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--request-file",required=True);parser.add_argument("--key",required=True,help="Stable run key; not a credential");parser.add_argument("--version",default="1.0.0");parser.add_argument("--timeout",type=float,default=30.0);args=parser.parse_args()
    voyager=VoyagerClient(os.environ["VOYAGER_API_URL"],api_key=os.environ.get("VOYAGER_API_KEY"),auth_header=os.environ.get("VOYAGER_AUTH_HEADER","Authorization"),auth_scheme=os.environ.get("VOYAGER_AUTH_SCHEME","Bearer"),timeout=args.timeout)
    sentinel_url=os.environ.get("SENTINEL_API_URL","http://127.0.0.1:8000");developer=SentinelClient(sentinel_url,os.environ["SENTINEL_DEVELOPER_API_KEY"]);worker=SentinelClient(sentinel_url,os.environ["SENTINEL_WORKER_API_KEY"])
    version=register_voyager(developer,args.version);print(json.dumps(monitored_execution(developer,worker,voyager,version,load_object(args.request_file),args.key),indent=2))
if __name__=="__main__":main()
