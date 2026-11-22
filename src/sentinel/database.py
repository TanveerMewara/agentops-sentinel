from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row


MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class Database:
    def __init__(self, database_url: str, *, min_connections: int = 1,
                 max_connections: int = 20):
        self.database_url = database_url
        self._min_connections = min_connections
        self._max_connections = max_connections
        self._pool = self._new_pool()
        self._pool_lock = Lock()
        self._opened = False

    def _new_pool(self):
        return ConnectionPool(self.database_url, min_size=self._min_connections,
            max_size=self._max_connections, open=False, timeout=10,
            kwargs={'row_factory': dict_row, 'connect_timeout': 5})

    def _open(self):
        if self._opened:
            return
        with self._pool_lock:
            if not self._opened:
                self._pool.open(wait=True, timeout=10)
                self._opened = True

    @contextmanager
    def connect(self):
        self._open()
        with self._pool.connection() as connection:
            yield connection

    def close(self):
        with self._pool_lock:
            if self._opened:
                self._pool.close()
                self._pool = self._new_pool()
                self._opened = False

    def migrate(self) -> None:
        with self.connect() as connection:
            # Serializes startup migrations in this database until commit. Read
            # the applied set after locking so a second replica sees the first.
            connection.execute("SELECT pg_advisory_xact_lock(739104275991)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS sentinel_schema_migrations (
                       version TEXT PRIMARY KEY,
                       applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                   )"""
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM sentinel_schema_migrations"
                ).fetchall()
            }
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name in applied:
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO sentinel_schema_migrations (version) VALUES (%s)",
                    (migration.name,),
                )
