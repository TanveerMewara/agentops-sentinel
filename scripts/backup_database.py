"""Back up the native development DB or rehearse restoration in a new temporary DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import native_postgres

BACKUPS = native_postgres.LOCAL / "backups"


def archive_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(BACKUPS.resolve()) or path.suffix != ".dump":
        raise ValueError("Use a .dump archive inside this project's .local/backups directory.")
    return path


def pg_environment(database, *, admin=False):
    config = native_postgres.settings()
    environment = os.environ.copy()
    environment.update(PGHOST="127.0.0.1", PGPORT=str(native_postgres.PORT), PGDATABASE=database,
        PGUSER="sentinel_admin" if admin else "sentinel_lesson",
        PGPASSWORD=config["admin_password" if admin else "app_password"], PGCONNECT_TIMEOUT="5")
    environment.pop("PGSERVICE", None)
    environment.pop("PGHOSTADDR", None)
    environment.pop("PGOPTIONS", None)
    return environment


def run_tool(name, arguments, environment):
    result = subprocess.run([str(native_postgres.BIN / (name + ".exe")), *map(str, arguments)],
        env=environment, cwd=native_postgres.ROOT, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.stderr.strip():
        # Preserve diagnostics locally; do not stream possible database content.
        (BACKUPS / f"{name}-{uuid4().hex}.log").write_text(result.stderr, encoding="utf-8")
        print(f"{name} emitted diagnostics; inspect the ignored backup log.")
    if result.returncode:
        raise RuntimeError(f"{name} failed with exit {result.returncode}; no database credentials were printed.")


def table_counts(connection):
    tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    return {row["tablename"]: connection.execute(sql.SQL("SELECT count(*) AS n FROM {}.{}").format(
        sql.Identifier("public"), sql.Identifier(row["tablename"]))).fetchone()["n"] for row in tables}


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup():
    native_postgres.start()
    BACKUPS.mkdir(parents=True, exist_ok=True)
    path = archive_path(BACKUPS / f"sentinel-{uuid4().hex}.dump")
    with psycopg.connect(native_postgres.dsn(), row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = connection.execute("SELECT pg_export_snapshot() AS snapshot").fetchone()["snapshot"]
        counts = table_counts(connection)
        run_tool("pg_dump", ["--format=custom", "--snapshot", snapshot, "--file", path],
                 pg_environment("sentinel_lesson"))
    manifest = {"format": "sentinel_native_backup_v1", "sha256": checksum(path),
                "table_counts": counts, "application_key_files_included": False}
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Database archive created:", path)
    print("Preserve the encryption key and authentication pepper separately; this archive does not include them.")
    return path


def rehearse(value):
    path = archive_path(value)
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "sentinel_native_backup_v1" or manifest.get("sha256") != checksum(path):
        raise ValueError("Backup manifest or checksum does not match.")
    native_postgres.start()
    target = "sentinel_restore_" + uuid4().hex
    created = False
    with psycopg.connect(native_postgres.dsn(admin=True), autocommit=True) as admin:
        try:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target)))
            created = True
            run_tool("pg_restore", ["--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction", "--dbname", target, path],
                     pg_environment(target, admin=True))
            with psycopg.connect(host="127.0.0.1", port=native_postgres.PORT, dbname=target,
                    user="sentinel_admin", password=native_postgres.settings()["admin_password"],
                    row_factory=dict_row, connect_timeout=5) as restored:
                counts = table_counts(restored)
                if counts != manifest["table_counts"]:
                    raise RuntimeError("Restored tables/row counts differ from the backup snapshot.")
                # Verify encrypted lead data remains decryptable with the separately
                # held key, without printing any contact content.
                encrypted = restored.execute("SELECT encrypted_customer_name FROM estate_leads LIMIT 1").fetchone()
                if encrypted:
                    import dev
                    from sentinel.provider_registry import CredentialCipher
                    CredentialCipher(dev.load_config()["credential_encryption_key"]).decrypt(encrypted["encrypted_customer_name"])
            print(f"PASS: restored {len(counts)} public tables with matching snapshot row counts and readable encrypted lead data.")
        finally:
            if created:
                # Only the database successfully created by this call can be dropped.
                # No existing target or production database can be supplied.
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
    print("Temporary rehearsal database removed. The source database was preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "rehearse", "check"])
    parser.add_argument("archive", nargs="?")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            backup()
        elif args.command == "check":
            rehearse(backup())
        elif args.archive:
            rehearse(args.archive)
        else:
            parser.error("rehearse requires an archive path")
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, psycopg.Error) as error:
        print("Backup/rehearsal failed:", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
