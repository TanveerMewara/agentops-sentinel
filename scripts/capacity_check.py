"""Reproducible local API capacity check using real HTTP and PostgreSQL."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

import dev

ROOT = Path(__file__).resolve().parents[1]
OPENER = build_opener(ProxyHandler({}))


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def request(url, key, path, body=None, timeout=10):
    payload = json.dumps(body).encode() if body is not None else None
    started = monotonic()
    with OPENER.open(Request(url + path, data=payload, headers={
        'X-API-Key': key, 'Content-Type': 'application/json'},
        method='POST' if body is not None else 'GET'), timeout=timeout) as response:
        return response.status, json.load(response), monotonic() - started


def wait_ready(url, process):
    deadline = monotonic() + 120
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Capacity API exited during startup.')
        try:
            with OPENER.open(url + '/health', timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        sleep(.2)
    raise RuntimeError('Capacity API did not become ready.')


def stop(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=int, default=80)
    parser.add_argument('--concurrency', type=int, default=8)
    parser.add_argument('--port', type=int, default=8030)
    parser.add_argument('--max-p95-ms', type=int, default=2000)
    args = parser.parse_args()
    if not 20 <= args.requests <= 400 or not 1 <= args.concurrency <= 32:
        raise SystemExit('Use 20-400 requests and concurrency 1-32.')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            raise SystemExit(f'Port {args.port} is already in use.')

    dev.setup(); config = dev.load_config(); environment = dev.child_environment()
    api_url = f'http://127.0.0.1:{args.port}'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'sentinel.asgi:app',
        '--host', '127.0.0.1', '--port', str(args.port), '--no-access-log'], cwd=ROOT,
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        start_new_session=os.name != 'nt')
    report_path = ROOT / '.local' / 'release-checks' / 'capacity.json'
    try:
        wait_ready(api_url, process)
        developer = config['keys']['developer']
        suffix = uuid4().hex[:12]
        _, agent, _ = request(api_url, developer, '/v1/agents', {
            'slug': 'capacity_' + suffix, 'display_name': 'Capacity fixture',
            'description': 'Bounded Stage 6 capacity evidence'})
        _, version, _ = request(api_url, developer,
            f"/v1/agents/{agent['agent_id']}/versions", {
            'version': '1.0.0', 'instructions': 'Capacity fixture; never executed.',
            'model_alias': 'external_agent', 'max_steps': 2})
        bodies = [(f'capacity-{suffix}-{index:04d}', {'sequence': index})
                  for index in range(args.requests)]

        def create(item):
            key, input_payload = item
            return key, request(api_url, developer, '/v1/runs', {
                'agent_version_id': version['agent_version_id'],
                'idempotency_key': key, 'input': input_payload})

        started = monotonic(); results = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(create, item) for item in bodies]
            for future in as_completed(futures):
                results.append(future.result())
        duration = monotonic() - started
        ids = {key: result[1]['run_id'] for key, result in results}
        latencies = [result[2] for _, result in results]

        replay_results = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(create, item) for item in bodies]
            for future in as_completed(futures):
                replay_results.append(future.result())
        replay_ok = all(ids[key] == result[1]['run_id'] for key, result in replay_results)
        report = {
            'schema_version': 1, 'requests': args.requests, 'concurrency': args.concurrency,
            'successful': len(results), 'errors': 0, 'replay_consistent': replay_ok,
            'duration_seconds': round(duration, 3),
            'throughput_requests_per_second': round(args.requests / duration, 2),
            'latency_ms': {'p50': round(statistics.median(latencies) * 1000, 2),
                'p95': round(percentile(latencies, .95) * 1000, 2),
                'max': round(max(latencies) * 1000, 2)},
            'limits': {'max_p95_ms': args.max_p95_ms, 'zero_errors': True,
                'idempotent_replay_required': True},
        }
        report['passed'] = (len(results) == args.requests and replay_ok and
                            report['latency_ms']['p95'] <= args.max_p95_ms)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, KeyError) as error:
        print(f'Capacity check failed ({type(error).__name__}).', file=sys.stderr)
        return 1
    finally:
        stop(process)


if __name__ == '__main__':
    raise SystemExit(main())
