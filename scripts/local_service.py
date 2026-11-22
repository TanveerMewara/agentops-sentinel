"""Start, inspect, and stop the Docker-free Sentinel process group."""
from __future__ import annotations
import argparse,json,os,subprocess,sys
from pathlib import Path
from time import sleep,time
from urllib.error import URLError
from urllib.request import ProxyHandler,build_opener
import dev,pilot

ROOT=Path(__file__).resolve().parents[1]; STATE=ROOT/'.local'/'service.json'; LOG=ROOT/'.local'/'service.log'
OPENER=build_opener(ProxyHandler({}))

def read_state():
    try: return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError,ValueError): return None

def alive(pid):
    if not pid or pid<=0:return False
    if os.name=='nt':
        result=subprocess.run(['powershell','-NoProfile','-Command',f"Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return result.stdout.strip()==str(pid)
    try: os.kill(pid,0);return True
    except OSError:return False

def verified_process(record):
    pid=record.get('pid') if record else None
    if not alive(pid):return False
    if os.name!='nt':return True
    script=f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; if($p){{[DateTimeOffset]$u=$p.StartTime.ToUniversalTime(); [math]::Floor($u.ToUnixTimeSeconds())}}"
    result=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:return abs(int(result.stdout.strip())-int(record.get('started_at_epoch',-1000)))<=3
    except ValueError:return False

def health(url):
    try:
        with OPENER.open(url,timeout=2) as response:return response.status==200
    except (URLError,TimeoutError,OSError):return False

def spawn(command,cwd,environment,log):
    started=int(time()); process=subprocess.Popen(command,cwd=cwd,env=environment,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
    return process,{'pid':process.pid,'started_at_epoch':started}

def terminate(record):
    if not verified_process(record):return not alive(record.get('pid'))
    pid=record['pid']
    if os.name=='nt':
        subprocess.run(['powershell','-NoProfile','-Command',f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
    else:os.killpg(pid,__import__('signal').SIGTERM)
    sleep(.5)
    if not alive(pid):return True
    sleep(2)
    return not alive(pid)

def start(args):
    current=read_state()
    if current and current.get('processes') and all(verified_process(item) for item in current['processes']):
        print(f"Sentinel service is already running at {current['web_url']}.");return 0
    if current and any(alive(item.get('pid')) for item in current.get('processes',[])):
        print('Refusing to replace partially running service state. Run stop first.');return 1
    STATE.unlink(missing_ok=True);pilot.check_ports([args.api_port,args.booking_port,args.web_port])
    node,frontend_cli=pilot.frontend_runtime()
    if not (ROOT/'web'/'dist'/'server').is_dir():print('Build the frontend before starting the service.');return 1
    dev.setup();backend=dev.child_environment();api=f'http://127.0.0.1:{args.api_port}';booking=f'http://127.0.0.1:{args.booking_port}';web=f'http://127.0.0.1:{args.web_port}'
    backend.update(SENTINEL_API_URL=api,SENTINEL_BOOKING_SERVICE_URL=booking,SENTINEL_ALLOWED_ORIGINS=f'{web},http://localhost:{args.web_port}')
    LOG.parent.mkdir(parents=True,exist_ok=True);log=LOG.open('a',encoding='utf-8');processes=[]
    try:
        for name,app,port,url in [('booking','lessons.booking_api_persistent:app',args.booking_port,booking),('api','sentinel.asgi:app',args.api_port,api)]:
            process,record=spawn([sys.executable,'-m','uvicorn',app,'--host','127.0.0.1','--port',str(port),'--no-access-log'],ROOT,backend,log);record['name']=name;processes.append(record);pilot.wait_ready(name,url+'/health',process)
        process,record=spawn([node,frontend_cli,'start','--hostname','127.0.0.1','--port',str(args.web_port)],ROOT/'web',pilot.frontend_environment(node),log);record['name']='dashboard';processes.append(record);pilot.wait_ready('dashboard',web,process)
        process,record=spawn([sys.executable,'-m','sentinel.worker'],ROOT,backend,log);record['name']='worker';processes.append(record)
        if args.demo:
            from pilot_demo import configure_demo
            from sentinel.client import SentinelClient
            configure_demo(SentinelClient(api,dev.load_config()['keys']['developer']))
        STATE.write_text(json.dumps({'schema_version':2,'api_url':api,'web_url':web,'log':str(LOG),'processes':processes},indent=2)+'\n',encoding='utf-8')
        print(f'Sentinel service started: {web} (API {api}).');return 0
    except Exception:
        for record in reversed(processes):terminate(record)
        STATE.unlink(missing_ok=True);print(f'Sentinel service failed to start. See {LOG}.');return 1
    finally:log.close()

def status():
    state=read_state();records=state.get('processes',[]) if state else [];running=bool(records and all(verified_process(item) for item in records));ready=bool(running and health(state['api_url']+'/health') and health(state['web_url']))
    print(json.dumps({'running':running,'ready':ready,'components':{item.get('name','unknown'):verified_process(item) for item in records},'web_url':state.get('web_url') if state else None,'api_url':state.get('api_url') if state else None},indent=2));return 0 if ready else 1

def stop():
    state=read_state()
    if not state:print('Sentinel service is not running.');return 0
    records=state.get('processes',[])
    if any(alive(item.get('pid')) and not verified_process(item) for item in records):print('Refusing to stop an unverified process; inspect the service state.');return 1
    stopped=all(terminate(item) for item in reversed(records))
    if not stopped:print('One or more Sentinel components did not stop cleanly.');return 1
    STATE.unlink(missing_ok=True);print('Sentinel service stopped.');return 0

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True);launch=sub.add_parser('start');launch.add_argument('--demo',action='store_true');launch.add_argument('--api-port',type=int,default=8000);launch.add_argument('--booking-port',type=int,default=8002);launch.add_argument('--web-port',type=int,default=3000);sub.add_parser('status');sub.add_parser('stop');args=parser.parse_args()
    return start(args) if args.command=='start' else status() if args.command=='status' else stop()

if __name__=='__main__':raise SystemExit(main())
