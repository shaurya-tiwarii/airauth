"""Database connection layer for AirAuth.

Local development uses SQLite via sqlite3. When TURSO_URL and TURSO_TOKEN
are set (the Render deployment), every table lives in Turso instead.

This exists because Render's free-tier filesystem is ephemeral: the local
SQLite files (accounts, documents, signatures, biometric templates, PDFs)
are wiped on every restart or redeploy. Turso survives restarts, so users
stop getting logged out and losing their data.

The two backends expose the same DB-API surface:
  connect()      -> connection whose fetchone()/fetchall() return dicts
                   (used by signstore.py)
  connect_raw()  -> plain DB-API connection, rows are tuples
                   (used by security.py's biometric vault)
"""
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "airauth.db")


def using_turso() -> bool:
    return bool(os.environ.get("TURSO_URL") and os.environ.get("TURSO_TOKEN"))


def _turso_url() -> str:
    url = os.environ["TURSO_URL"].strip()
    # The Python client speaks HTTPS; accept the canonical libsql:// form too.
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url


def connect_raw(path=None):
    """Plain DB-API connection. Row type is backend-native (tuples).

    path overrides the local SQLite file (used by tests). Ignored when
    Turso is configured, since there is only one shared database.
    """
    if using_turso():
        import libsql
        return libsql.connect(
            _turso_url(),
            auth_token=os.environ["TURSO_TOKEN"],
        )
    return sqlite3.connect(path or DB_FILE)


class _DictCursor:
    """Cursor wrapper: fetchone()/fetchall() return dicts instead of tuples."""

    def __init__(self, cursor):
        self._cursor = cursor

    def _convert(self, rows):
        desc = self._cursor.description
        cols = [d[0] for d in desc] if desc else []
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append(r)
            elif hasattr(r, "keys"):  # sqlite3.Row
                out.append(dict(r))
            else:  # plain tuple (libsql)
                out.append(dict(zip(cols, r)))
        return out

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._convert([row])[0] if row is not None else None

    def fetchall(self):
        return self._convert(self._cursor.fetchall())

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _DictConnection:
    """Connection wrapper: execute()/cursor() return dict-yielding cursors."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs):
        return _DictCursor(self._conn.execute(*args, **kwargs))

    def cursor(self):
        return _DictCursor(self._conn.cursor())

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Mirror sqlite3 semantics: commit on clean exit, rollback on error.
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
        return False

    def __getattr__(self, name):
        return getattr(self._conn, name)


def connect():
    """Connection whose cursors return dicts from fetchone()/fetchall().

    Local SQLite keeps its native behaviour (sqlite3.Row -> dict()).
    Turso connections are wrapped so the rest of the code is unchanged.
    """
    if using_turso():
        return _DictConnection(connect_raw())
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn
