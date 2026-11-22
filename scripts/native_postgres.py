"""Manage this project's native Windows development PostgreSQL only."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import zipfile

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
BIN = LOCAL / "pgsql" / "bin"
DATA = LOCAL / "postgres-data"
CONFIG = LOCAL / "postgres-config.json"
PORT = 55432


def run_pg(program, *args):
    result = subprocess.run([str(BIN / (program + ".exe")), *map(str, args)],
                            cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(f"{program} failed with exit {result.returncode}; inspect .local/postgres.log.")


def settings():
    if not CONFIG.exists():
        raise RuntimeError("Run setup first. Local credentials have not been created.")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def dsn(admin=False):
    config = settings()
    return make_conninfo(host="127.0.0.1", port=PORT,
                         user="sentinel_admin" if admin else "sentinel_lesson",
                         password=config["admin_password" if admin else "app_password"],
                         dbname="postgres" if admin else "sentinel_lesson", connect_timeout=5)


def start():
    # pg_ctl can report a stale/non-owner status on Windows even while this
    # project's server is healthy. Prefer an authenticated readiness check so
    # setup remains idempotent across shells and automation contexts.
    if CONFIG.exists():
        try:
            with psycopg.connect(dsn(admin=True)) as connection:
                connection.execute("SELECT 1")
            print("Project PostgreSQL is already running.")
            return
        except psycopg.OperationalError:
            pass
    status = subprocess.run([str(BIN / "pg_ctl.exe"), "status", "-D", str(DATA)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if status.returncode == 0:
        print("Project PostgreSQL is already running.")
        return
    run_pg("pg_ctl", "start", "-D", DATA, "-l", LOCAL / "postgres.log",
           "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "-t", "30")


def stop():
    run_pg("pg_ctl", "stop", "-D", DATA, "-m", "fast", "-w", "-t", "30")


def setup():
    LOCAL.mkdir(exist_ok=True)
    if not (LOCAL / "server-extracted.txt").exists():
        archive = LOCAL / "postgresql-17.11.zip"
        if not archive.exists():
            raise RuntimeError("Download the official archive as documented in docs/local-postgresql.md.")
        print("Extracting native PostgreSQL binaries...", flush=True)
        with zipfile.ZipFile(archive) as bundle:
            server_files = [entry for entry in bundle.infolist()
                            if entry.filename.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/"))
                            or (entry.filename.startswith("pgsql/") and entry.filename.count("/") == 1)]
            local_root = LOCAL.resolve()
            for entry in server_files:
                destination = (LOCAL / entry.filename).resolve()
                if not destination.is_relative_to(local_root):
                    raise RuntimeError("Archive entry escapes the project-local directory.")
            print(f"Extracting {len(server_files)} server entries...", flush=True)
            bundle.extractall(LOCAL, members=server_files)
        (LOCAL / "server-extracted.txt").write_text("PostgreSQL 17.11 server components", encoding="utf-8")
    if not CONFIG.exists():
        with CONFIG.open("x", encoding="utf-8") as file:
            json.dump({"admin_password": secrets.token_urlsafe(32),
                       "app_password": secrets.token_urlsafe(32)}, file)
    if not (DATA / "PG_VERSION").exists():
        password_file = LOCAL / "initdb-password.tmp"
        try:
            password_file.write_text(settings()["admin_password"], encoding="utf-8")
            run_pg("initdb", "-D", DATA, "-U", "sentinel_admin",
                   "--pwfile", password_file, "--auth-host=scram-sha-256",
                   "--auth-local=scram-sha-256", "--encoding=UTF8", "--locale=C")
        finally:
            password_file.unlink(missing_ok=True)
    start()
    with psycopg.connect(dsn(admin=True), autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname = 'sentinel_lesson'").fetchone():
            connection.execute(sql.SQL("CREATE ROLE sentinel_lesson LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Literal(settings()["app_password"])))
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname = 'sentinel_lesson'").fetchone():
            connection.execute("CREATE DATABASE sentinel_lesson OWNER sentinel_lesson")
    print("Native PostgreSQL ready on localhost:55432. Credentials remain in ignored .local config.")


def run_checks():
    start()
    environment = os.environ.copy()
    environment["SENTINEL_LESSON_DATABASE_URL"] = dsn()
    subprocess.run([sys.executable, "lessons/03_persistence_checks.py"],
                   cwd=ROOT, env=environment, check=True, timeout=90)
    with psycopg.connect(dsn()) as connection:
        before = connection.execute("SELECT booking_id FROM lesson_bookings ORDER BY booking_id").fetchall()
    stop()
    start()
    with psycopg.connect(dsn()) as connection:
        after = connection.execute("SELECT booking_id FROM lesson_bookings ORDER BY booking_id").fetchall()
    if not before or before != after:
        raise RuntimeError("Database restart persistence check failed.")
    print(f"PASS: {len(after)} fictional booking records survive a PostgreSQL restart.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "start", "stop", "check", "serve", "status"])
    args = parser.parse_args()
    if args.command == "setup":
        setup()
    elif args.command == "start":
        start()
    elif args.command == "stop":
        stop()
    elif args.command == "check":
        run_checks()
    elif args.command == "status":
        with psycopg.connect(dsn()) as connection:
            version = connection.execute("SHOW server_version").fetchone()[0]
        print(f"Project PostgreSQL {version} is reachable on localhost:{PORT}.")
    else:
        start()
        environment = os.environ.copy()
        environment["SENTINEL_LESSON_DATABASE_URL"] = dsn()
        subprocess.run([sys.executable, "-m", "uvicorn", "lessons.booking_api_persistent:app",
                        "--host", "127.0.0.1", "--port", "8001"],
                       cwd=ROOT, env=environment, check=True)


if __name__ == "__main__":
    main()

