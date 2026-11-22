"""Enable exact pgvector queries on a database that already offers the extension."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import native_postgres
from sentinel.database import Database


def main():
    database = Database(os.environ.get("SENTINEL_DATABASE_URL") or native_postgres.dsn())
    database.migrate()
    with database.connect() as connection:
        available = connection.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name='vector'"
        ).fetchone()
        if not available:
            raise RuntimeError(
                "pgvector is not installed on this PostgreSQL server. "
                "Use a pgvector-enabled PostgreSQL deployment first."
            )
        connection.execute(
            (ROOT / "src" / "sentinel" / "vector" / "001_pgvector.sql")
            .read_text(encoding="utf-8")
        )
    print("pgvector enabled and existing embeddings copied into vector(512).")


if __name__ == "__main__":
    main()
