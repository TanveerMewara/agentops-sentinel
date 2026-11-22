"""Report optional PostgreSQL extensions used by later Sentinel milestones."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import native_postgres
from sentinel.database import Database


def main():
    database = Database(native_postgres.dsn())
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT name, default_version, installed_version
               FROM pg_available_extensions
               WHERE name IN ('vector', 'pg_trgm', 'unaccent') ORDER BY name"""
        ).fetchall()
    for row in rows:
        print(
            f"{row['name']}: available={row['default_version']} "
            f"installed={row['installed_version'] or 'no'}"
        )


if __name__ == "__main__":
    main()
