"""Start the complete fictional local pilot without Docker. Ctrl+C stops children."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import dev
from sentinel.client import NoRedirect, SentinelClient, SentinelError

ROOT = Path(__file__).resolve().parents[1]
OPENER = build_opener(ProxyHandler({}), NoRedirect())


def frontend_runtime():
    candidates = sorted((ROOT / ".local").glob("node-*-win-x64/node.exe"), reverse=True)
    node = str(candidates[0]) if candidates else shutil.which("node")
    cli = ROOT / "web" / "node_modules" / "vinext" / "dist" / "cli.js"
    if not node or not cli.is_file():
        raise RuntimeError("Install Node and frontend dependencies before starting the pilot.")
    return node, str(cli)


def frontend_environment(node):
    # Frontend tooling must not inherit backend database, API or encryption keys.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
               "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment["PATH"] = str(Path(node).parent) + os.pathsep + environment.get("PATH", "")
    environment["NODE_ENV"] = "production"
    return environment


def check_ports(ports):
    if len(set(ports)) != len(ports):
        raise RuntimeError("Each component needs a different port.")
    for port in ports:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is already in use. Existing services were left running.")


def start(command, cwd, environment):
    return subprocess.Popen(command, cwd=cwd, env=environment,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            start_new_session=os.name != "nt")


def stop(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Only the still-running process created by this launcher and its children.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    else:
        import signal
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=10)


def wait_ready(name, url, process, seconds=240):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited during startup. Use the individual service command for diagnostics.")
        try:
            with OPENER.open(url, timeout=2) as response:
                if response.status == 200:
                    print(f"Ready: {name}", flush=True)
                    return
        except (URLError, TimeoutError, OSError):
            pass
        sleep(0.25)
    raise RuntimeError(f"{name} did not become ready within {seconds} seconds.")


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError("Use a port between 1024 and 65535.")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify startup and identity, then stop owned services")
    parser.add_argument("--demo", action="store_true", help="configure a fictional property-bound reference agent and listing")
    parser.add_argument("--preview", action="store_true", help="show the dashboard and API with automatic worker dispatch paused")
    parser.add_argument("--api-port", type=port, default=8000)
    parser.add_argument("--booking-port", type=port, default=8002)
    parser.add_argument("--web-port", type=port, default=3000)
    args = parser.parse_args()
    children = []
    try:
        check_ports([args.api_port, args.booking_port, args.web_port])
        node, frontend_cli = frontend_runtime()
        if not (ROOT / "web" / "dist" / "server").is_dir():
            raise RuntimeError("Build the frontend with npm run build before starting the pilot.")
        dev.setup()
        environment = dev.child_environment()
        api_url = f"http://127.0.0.1:{args.api_port}"
        booking_url = f"http://127.0.0.1:{args.booking_port}"
        web_url = f"http://127.0.0.1:{args.web_port}"
        environment.update(SENTINEL_API_URL=api_url, SENTINEL_BOOKING_SERVICE_URL=booking_url,
                           SENTINEL_ALLOWED_ORIGINS=f"{web_url},http://localhost:{args.web_port}")
        for name, app, number, base in [
            ("booking service", "lessons.booking_api_persistent:app", args.booking_port, booking_url),
            ("Sentinel API", "sentinel.asgi:app", args.api_port, api_url),
        ]:
            process = start([sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1",
                             "--port", str(number), "--no-access-log"], ROOT, environment)
            children.append(process)
            wait_ready(name, base + "/health", process)
        frontend = start([node, frontend_cli, "start", "--hostname", "127.0.0.1",
                          "--port", str(args.web_port)], ROOT / "web", frontend_environment(node))
        children.append(frontend)
        wait_ready("dashboard", web_url, frontend)
        # Check real authentication without printing tokens or issuing a write.
        config = dev.load_config()
        identity = SentinelClient(api_url, config["keys"]["developer"]).identity()
        if identity["role"] != "developer":
            raise RuntimeError("The local developer identity check failed.")
        if args.demo:
            from pilot_demo import configure_demo
            client = SentinelClient(api_url, config["keys"]["developer"])
            configured = configure_demo(client)
            if args.check and configure_demo(client) != configured:
                raise RuntimeError("Fictional demo configuration did not replay consistently.")
            print("Fictional demo agent and metro listing are configured.", flush=True)
        if args.check:
            print("Local pilot startup and authenticated identity passed. Services will stop.", flush=True)
            return 0
        if not args.preview:
            worker = start([sys.executable, "-m", "sentinel.worker"], ROOT, environment)
            children.append(worker)
        else:
            print("UI preview: automatic worker dispatch is paused.", flush=True)
        print(f"Open {web_url} and connect to {api_url}. Ctrl+C stops this pilot.", flush=True)
        print("Use scripts/dev.py show-keys separately for local dashboard access.", flush=True)
        print("Bookings are fictional; follow-up emails remain internal drafts.", flush=True)
        while True:
            if any(process.poll() is not None for process in children):
                raise RuntimeError("A pilot component stopped. All owned components will stop.")
            sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping local pilot...", flush=True)
        return 0
    except (RuntimeError, OSError, SentinelError) as error:
        print(str(error) if isinstance(error, RuntimeError) else f"Pilot failed ({type(error).__name__}).", flush=True)
        return 1
    finally:
        for process in reversed(children):
            stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
