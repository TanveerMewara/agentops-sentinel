"""Measure Voyager AI directly and with AgentOps Sentinel monitoring."""
from __future__ import annotations
import argparse,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"src"))
from benchmarks.metrics import distribution,percent_change
from benchmarks.reporting import write_json
from examples.voyager_ai_agent import VoyagerClient,load_object,monitored_execution,register_voyager
from sentinel.client import SentinelClient
REPORT=ROOT/".local"/"voyager-benchmark"/"latest.json"

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--request-file",required=True);parser.add_argument("--samples",type=int,default=10);parser.add_argument("--warmups",type=int,default=1);parser.add_argument("--version",default="1.0.0");parser.add_argument("--timeout",type=float,default=30.0);args=parser.parse_args()
    if not 3<=args.samples<=100 or not 0<=args.warmups<=10:raise ValueError("Use 3-100 samples and 0-10 warmups.")
    payload=load_object(args.request_file);voyager=VoyagerClient(os.environ["VOYAGER_API_URL"],api_key=os.environ.get("VOYAGER_API_KEY"),auth_header=os.environ.get("VOYAGER_AUTH_HEADER","Authorization"),auth_scheme=os.environ.get("VOYAGER_AUTH_SCHEME","Bearer"),timeout=args.timeout)
    sentinel_url=os.environ.get("SENTINEL_API_URL","http://127.0.0.1:8000");developer=SentinelClient(sentinel_url,os.environ["SENTINEL_DEVELOPER_API_KEY"]);worker=SentinelClient(sentinel_url,os.environ["SENTINEL_WORKER_API_KEY"])
    if developer.identity()["organization_id"]!=worker.identity()["organization_id"]:raise ValueError("Sentinel developer and worker keys must share an organization.")
    version=register_voyager(developer,args.version)
    for _ in range(args.warmups):voyager.invoke(payload)
    benchmark_id=uuid4().hex;direct_ms=[];monitored_ms=[];end_to_end=[];create_ms=[];submit_ms=[];complete_ms=[];run_ids=[];fingerprints=set()
    for index in range(args.samples):
        _,elapsed,_=voyager.invoke(payload);direct_ms.append(elapsed);started=perf_counter()
        measured=monitored_execution(developer,worker,voyager,version,payload,f"voyager-benchmark-{benchmark_id}-{index}")
        end_to_end.append((perf_counter()-started)*1000);monitored_ms.append(measured["voyager_ms"]);create_ms.append(measured["sentinel_create_ms"]);submit_ms.append(measured["sentinel_submit_ms"]);complete_ms.append(measured["sentinel_complete_ms"]);run_ids.append(measured["run_id"]);fingerprints.add(measured["safe_output"]["response_sha256"])
    direct=distribution(direct_ms);monitored=distribution(monitored_ms)
    report={"schema_version":1,"run_id":benchmark_id,"completed_at":datetime.now(timezone.utc).isoformat(),"samples":args.samples,"voyager":{"direct_latency_ms":direct,"instrumented_call_latency_ms":monitored,"mean_call_delta_ms":round(monitored["mean"]-direct["mean"],6),"mean_call_delta_percent":percent_change(direct["mean"],monitored["mean"]),"distinct_response_fingerprints":len(fingerprints)},"sentinel":{"run_create_ms":distribution(create_ms),"trace_submit_ms":distribution(submit_ms),"run_complete_ms":distribution(complete_ms),"end_to_end_monitored_ms":distribution(end_to_end),"completed_runs":len(run_ids)},"evidence_boundary":["Voyager request and response bodies are excluded from this report and Sentinel.","Direct and instrumented calls are alternating repeated requests, not identical paired executions.","Results describe this endpoint, payload, machine, network, and run only.","Sentinel ingestion is out of the agent critical path unless the integration chooses to wait for it."]}
    write_json(REPORT,report);print(json.dumps(report,indent=2));print(f"Report: {REPORT.relative_to(ROOT)}")
if __name__=="__main__":main()
