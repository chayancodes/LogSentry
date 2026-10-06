"""
Member 3 (cont.) - Query Engine
---------------------------------
Job: translate CLI-style filter options (level, source, keyword, time range,
anomalies-only) into a parameterized SQL query against the `logs` table, and
hand back plain Python dicts.

Public entry points
-------------------
query_logs(conn, **filters)    -> list[dict]
count_logs_matching(conn, **filters) -> int
count_by_level(conn, **filters)      -> dict
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional, Tuple

MAX_LIMIT = 10_000


def _normalize_ts(value: str) -> str:
    """Stored timestamps use the ISO 'T' separator; accept a space too."""
    return value.strip().replace(" ", "T", 1)


def _escape_like(text: str) -> str:
    """Make %, _ and the escape char itself match literally inside LIKE."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_where(
    level: Optional[str],
    source: Optional[str],
    contains: Optional[str],
    since: Optional[str],
    until: Optional[str],
    anomalies_only: bool,
) -> Tuple[str, dict]:
    clauses: list = []
    params: dict = {}

    if level:
        clauses.append("level = :level")
        params["level"] = level.upper()
    if source:
        clauses.append("source = :source")
        params["source"] = source
    if contains:
        # LIKE is already case-insensitive for ASCII in SQLite.
        clauses.append("message LIKE :contains ESCAPE '\\'")
        params["contains"] = f"%{_escape_like(contains)}%"
    if since:
        clauses.append("timestamp >= :since")
        params["since"] = _normalize_ts(since)
    if until:
        clauses.append("timestamp <= :until")
        params["until"] = _normalize_ts(until)
    if anomalies_only:
        clauses.append("is_anomaly = 1")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def query_logs(
    conn: sqlite3.Connection,
    level: Optional[str] = None,
    source: Optional[str] = None,
    contains: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    anomalies_only: bool = False,
    limit: int = 100,
    order: str = "desc",
    offset: int = 0,
) -> List[dict]:
    """
    Search stored logs with optional filters.

    Parameters
    ----------
    level : only rows with this level (case-insensitive, e.g. "error")
    source : only rows from this exact source/component name
    contains : literal substring to find in the message (case-insensitive;
               %, _ are treated as ordinary characters)
    since / until : ISO timestamp bounds (inclusive), e.g. "2026-08-19T00:00:00"
    anomalies_only : if True, only rows flagged as anomalies
    limit : max rows to return (1..MAX_LIMIT)
    order : "asc" or "desc" by timestamp
    offset : rows to skip, for paging

    Returns
    -------
    list[dict] - matching rows as plain dictionaries.
    """
    if order.lower() not in ("asc", "desc"):
        raise ValueError("order must be 'asc' or 'desc'")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be >= 0")

    where_sql, params = _build_where(level, source, contains, since, until, anomalies_only)
    direction = order.upper()

    # `id` is a tie-breaker so rows with equal timestamps come back in a
    # stable order (and paging never skips/duplicates rows).
    sql = f"""
        SELECT id, timestamp, level, source, message, is_anomaly, anomaly_score
        FROM logs
        {where_sql}
        ORDER BY timestamp {direction}, id {direction}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = min(limit, MAX_LIMIT)
    params["offset"] = offset

    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def count_logs_matching(
    conn: sqlite3.Connection,
    level: Optional[str] = None,
    source: Optional[str] = None,
    contains: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    anomalies_only: bool = False,
) -> int:
    """How many rows match the same filters query_logs accepts (ignores limit)."""
    where_sql, params = _build_where(level, source, contains, since, until, anomalies_only)
    return conn.execute(f"SELECT COUNT(*) AS n FROM logs {where_sql}", params).fetchone()["n"]


def count_by_level(
    conn: sqlite3.Connection,
    source: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict:
    """Return a {level: count} summary (optionally for one source / time range)."""
    where_sql, params = _build_where(None, source, None, since, until, False)
    rows = conn.execute(
        f"SELECT level, COUNT(*) AS n FROM logs {where_sql} GROUP BY level ORDER BY n DESC, level",
        params,
    ).fetchall()
    return {row["level"]: row["n"] for row in rows}
