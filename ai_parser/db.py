"""
Member 3 - SQLite Storage + Schema + Indexes
------------------------------------------------
Job: persist parsed log records (the shared dict schema) into a single local
SQLite file so they can be searched later. No separate database server is
needed - sqlite3 ships with Python.

Public entry points
--------------------
get_connection(db_path)            -> sqlite3.Connection
init_db(conn)                      -> creates the `logs` table + indexes
insert_record(conn, record, ...)   -> inserts one parsed record, returns its id
insert_many(conn, records)         -> bulk-inserts parsed records in ONE transaction
mark_anomalies(conn, flags)        -> persists anomaly flags/scores for stored rows
count_logs(conn)                   -> total number of stored rows
clear_logs(conn)                   -> wipe all rows (tests / demos)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Tuple, Union

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    level         TEXT NOT NULL,
    source        TEXT NOT NULL,
    message       TEXT NOT NULL,
    is_anomaly    INTEGER NOT NULL DEFAULT 0,
    anomaly_score REAL
);
"""

# Single-column indexes (kept from v1) + composite indexes that match the
# query engine's access pattern: "filter by X, newest first".
INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);",
    "CREATE INDEX IF NOT EXISTS idx_logs_source ON logs(source);",
    "CREATE INDEX IF NOT EXISTS idx_logs_level_ts ON logs(level, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_logs_source_ts ON logs(source, timestamp);",
    # Partial index: only anomalous rows, so `--anomalies-only` stays fast
    # and the index stays tiny.
    "CREATE INDEX IF NOT EXISTS idx_logs_anomaly_ts ON logs(timestamp) WHERE is_anomaly = 1;",
)

REQUIRED_FIELDS = ("timestamp", "level", "source", "message")

_INSERT_SQL = """
    INSERT INTO logs (timestamp, level, source, message, is_anomaly, anomaly_score)
    VALUES (:timestamp, :level, :source, :message, :is_anomaly, :anomaly_score)
"""


def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open (and create, if needed) the SQLite database file."""
    path = Path(db_path)
    if str(db_path) != ":memory:" and path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if str(db_path) != ":memory:":
        # WAL lets `watch` keep writing while `query` reads from another terminal.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the `logs` table and its indexes if they don't already exist."""
    with conn:
        conn.execute(SCHEMA)
        for index_sql in INDEXES:
            conn.execute(index_sql)


def _clean(record: dict, is_anomaly: bool = False,
           anomaly_score: Optional[float] = None) -> dict:
    """Validate a parsed record and turn it into SQL parameters."""
    missing = [f for f in REQUIRED_FIELDS if record.get(f) in (None, "")]
    if missing:
        raise ValueError(f"record is missing required field(s): {', '.join(missing)}")
    return {
        "timestamp": str(record["timestamp"]),
        "level": str(record["level"]).upper(),
        "source": str(record["source"]),
        "message": str(record["message"]),
        "is_anomaly": int(bool(record.get("is_anomaly", is_anomaly))),
        "anomaly_score": record.get("anomaly_score", anomaly_score),
    }


def insert_record(
    conn: sqlite3.Connection,
    record: dict,
    is_anomaly: bool = False,
    anomaly_score: Optional[float] = None,
    commit: bool = True,
) -> int:
    """
    Insert one parsed record (the shared timestamp/level/source/message
    dict) into the `logs` table. Returns the new row's id.

    Pass ``commit=False`` when inserting many rows in a loop and call
    ``conn.commit()`` once at the end - committing per row is ~100x slower.
    """
    params = _clean(record, is_anomaly, anomaly_score)
    if commit:
        with conn:
            cursor = conn.execute(_INSERT_SQL, params)
    else:
        cursor = conn.execute(_INSERT_SQL, params)
    return cursor.lastrowid


def insert_many(conn: sqlite3.Connection, records: Iterable[dict]) -> int:
    """
    Bulk-insert parsed records in a single transaction. Returns the number
    inserted. If any record is invalid nothing is inserted (all-or-nothing).
    Optional ``is_anomaly`` / ``anomaly_score`` keys on a record are kept.
    """
    rows = [_clean(r) for r in records]
    with conn:
        conn.executemany(_INSERT_SQL, rows)
    return len(rows)


def mark_anomalies(
    conn: sqlite3.Connection, flags: Iterable[Tuple[int, bool, Optional[float]]]
) -> int:
    """
    Persist anomaly-detector output for rows that are already stored.

    ``flags`` is an iterable of ``(row_id, is_anomaly, anomaly_score)``.
    Returns the number of rows updated.
    """
    data = [(int(bool(a)), s, int(i)) for i, a, s in flags]
    with conn:
        conn.executemany(
            "UPDATE logs SET is_anomaly = ?, anomaly_score = ? WHERE id = ?", data
        )
    return len(data)


def count_logs(conn: sqlite3.Connection) -> int:
    """Total number of stored rows."""
    return conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"]


def clear_logs(conn: sqlite3.Connection) -> None:
    """Wipe all rows - handy for tests and demos."""
    with conn:
        conn.execute("DELETE FROM logs;")
