"""Run: python lessons/03_persistence_checks.py (requires lesson PostgreSQL)."""
import importlib.util
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lessons.booking_api_persistent import connect, initialize_database

spec = importlib.util.spec_from_file_location("http_lesson", ROOT / "lessons/02_http_client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def start_server(port):
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "lessons.booking_api_persistent:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("API exited before startup; check PostgreSQL is running.")
            try:
                client.request_json(f"http://127.0.0.1:{port}", "/health", timeout=0.5)
                return process
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("API did not become ready.")
    except BaseException:
        stop_server(process)
        raise


def stop_server(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def main():
    initialize_database()
    # Reserve an available port; no pre-existing user server is stopped.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = start_server(port)
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "lessons/02_http_client.py"), "--base-url", base],
            check=True, timeout=30,
        )
        operation = uuid4().hex
        payload = {"customer": f"restart-{operation}", "slot": "2030-01-15 10:00", "operation_id": operation}
        # Commit the booking, lose the response, then kill the API process.
        try:
            client.request_json(base, "/bookings", {**payload, "response_delay_seconds": 5}, timeout=0.5)
        except TimeoutError:
            pass
        else:
            raise AssertionError("Expected timeout")
        with connect() as connection:
            saved = connection.execute(
                "SELECT booking_id FROM lesson_bookings WHERE operation_id = %s", (operation,)
            ).fetchone()
        assert saved is not None
        stop_server(server)
        server = start_server(port)
        replay = client.request_json(base, "/bookings", payload)
        assert replay["booking_id"] == saved["booking_id"]
        print("PASS: committed booking survives API kill and retry returns the same ID.")

        operation = uuid4().hex
        payload = {"customer": f"parallel-{operation}", "slot": "2030-01-15 10:00", "operation_id": operation}
        barrier = Barrier(8)
        def send(_):
            barrier.wait(timeout=10)
            return client.request_json(base, "/bookings", payload, timeout=15)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(send, range(8)))
        assert len({result["booking_id"] for result in results}) == 1
        with connect() as connection:
            count = connection.execute(
                "SELECT count(*) AS total FROM lesson_bookings WHERE operation_id = %s", (operation,)
            ).fetchone()["total"]
        assert count == 1
        print("PASS: eight simultaneous requests create one booking.")

        operation = uuid4().hex
        class DeliberateFailure(Exception):
            pass
        try:
            with connect() as connection:
                connection.execute(
                    "INSERT INTO lesson_bookings VALUES (%s, %s, %s, %s)",
                    (str(uuid4()), operation, "rollback-test", "2030-01-15 10:00"),
                )
                raise DeliberateFailure()
        except DeliberateFailure:
            pass
        with connect() as connection:
            assert connection.execute(
                "SELECT 1 FROM lesson_bookings WHERE operation_id = %s", (operation,)
            ).fetchone() is None
        print("PASS: failed transaction leaves no booking or operation ID.")
        print("All Lesson 3 checks passed. Fictional successful test bookings are retained.")
    finally:
        stop_server(server)


if __name__ == "__main__":
    main()
