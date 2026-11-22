"""Two competing migration starters in an owned temporary native database."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sentinel.database import Database, MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import native_postgres


def main():
    native_postgres.setup()
    admin_dsn = native_postgres.dsn(admin=True)
    target = "sentinel_migrations_" + uuid4().hex[:16]
    created = False
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
            created = True
        connection_info = conninfo_to_dict(admin_dsn)
        connection_info["dbname"] = target
        database = Database(make_conninfo(**connection_info))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(database.migrate) for _ in range(2)]
            for future in futures:
                future.result(timeout=90)
        expected = {path.name for path in MIGRATIONS.glob("*.sql")}
        with database.connect() as connection:
            applied = {row["version"] for row in connection.execute("SELECT version FROM sentinel_schema_migrations").fetchall()}
            assert applied == expected
            constraint = connection.execute("""SELECT confdeltype FROM pg_constraint
                WHERE conname='sentinel_request_limits_api_key_id_fkey'""").fetchone()
            assert constraint["confdeltype"] == "c"
        database.migrate()
        with database.connect() as connection:
            assert connection.execute("SELECT count(*) AS count FROM sentinel_schema_migrations").fetchone()["count"] == len(expected)
        print(f"PASS: competing native startup migrations applied {len(expected)} versions once, replayed idempotently, and verified counter cleanup constraints.")
    finally:
        # Only the uniquely named database successfully created by this script
        # is eligible for cleanup. Never target the configured source database.
        if created:
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (target,))
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))


if __name__ == "__main__":
    main()
