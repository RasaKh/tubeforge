from contextlib import closing
import sqlite3
import threading

from .config import DB_PATH

# ═══════════════════════════════════════════════════════════════════════════
#  SQLITE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

_db_lock = threading.RLock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    with _db_lock, closing(db()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT, title TEXT, cmd TEXT, cwd TEXT,
            status TEXT, rc INTEGER,
            created REAL, started REAL, finished REAL,
            spec TEXT, meta TEXT
        );
        CREATE TABLE IF NOT EXISTS presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT, name TEXT, data TEXT, created REAL,
            UNIQUE(kind, name)
        );
        CREATE TABLE IF NOT EXISTS pipelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, data TEXT, created REAL
        );
        CREATE TABLE IF NOT EXISTS url_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, title TEXT, uploader TEXT, duration REAL,
            thumb TEXT, ts REAL
        );
        CREATE TABLE IF NOT EXISTS snippets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, body TEXT, tags TEXT, created REAL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created DESC);
        CREATE INDEX IF NOT EXISTS idx_hist_ts ON url_history(ts DESC);
        """)


db_init()


def db_exec(sql, args=()):
    # `with conn` commits the transaction but does not close the handle, so the
    # connection has to be closed explicitly or file descriptors accumulate.
    with _db_lock, closing(db()) as conn:
        with conn:
            return conn.execute(sql, args).lastrowid


def db_query(sql, args=()):
    with _db_lock, closing(db()) as conn:
        with conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]


