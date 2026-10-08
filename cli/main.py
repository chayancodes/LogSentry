"""
LogSentry - command line interface
==================================

Wires every module together into one tool::

    logsentry init-db  --db logsentry.db
    logsentry ingest   logsentry/data/sample.log --db logsentry.db
    logsentry query    --db logsentry.db --level ERROR
    logsentry stats    --db logsentry.db
    logsentry watch    app.log --db logsentry.db --threshold 5 --window 300
    logsentry demo
    logsentry clear    --db logsentry.db --yes

Without installing, run it as ``python -m logsentry.cli.main <command> ...``
from the project folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    import click
except ImportError:  # friendly message instead of a raw traceback (error E-37)
    sys.stderr.write(
        "LogSentry needs the 'click' library, which is not installed for this Python.\n"
        f"  Python in use: {sys.executable}\n"
        "  Fix (run in the project folder):\n"
        f'      "{sys.executable}" -m pip install -r requirements.txt\n'
        "  or double-click setup.bat on Windows.\n"
    )
    raise SystemExit(1)

# Make the sibling packages (alerting, parser, ...) importable no matter where
# the command is started from.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --- optional pretty output -------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table

    HAS_RICH = True
except ImportError:  # the CLI still works (plain tables) without rich
    HAS_RICH = False

from alerting import LiveMonitor, PatternRule, RulesEngine, ThresholdRule
from ai_parser import detect_and_store, fallback_parse_line
from ingestion.ingestor import LogIngestor, UnsupportedFileTypeError
from parser import parse_line
from query import count_by_level, count_logs_matching, query_logs
from query.query_engine import MAX_LIMIT
from storage import (clear_logs, count_logs, find_ingested_file, get_connection, init_db,
                     insert_record, record_ingested_file)

DEFAULT_DB = "logsentry.db"
SAMPLE_LOG = Path(__file__).resolve().parent.parent / "logsentry" / "data" / "sample.log"
LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _connect(db: str, must_exist: bool = False, create_schema: bool = False):
    """Open the database, turning low-level problems into friendly CLI errors."""
    if must_exist and db != ":memory:" and not os.path.isfile(db):
        raise click.ClickException(
            f"Database '{db}' not found. Create it first with:  logsentry init-db --db {db}"
        )
    try:
        conn = get_connection(db)
        if create_schema:
            init_db(conn)
        else:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs'"
            ).fetchone()
            if not has_table and must_exist:
                conn.close()
                raise click.ClickException(
                    f"Database '{db}' has no 'logs' table. Run:  logsentry init-db --db {db}"
                )
        return conn
    except sqlite3.Error as exc:
        raise click.ClickException(f"Cannot use database '{db}': {exc}")
    except OSError as exc:
        raise click.ClickException(f"Cannot create database '{db}': {exc}")


def _check_ts(ctx, param, value):
    """click callback: accept YYYY-MM-DD, 'YYYY-MM-DD HH:MM[:SS]' or ISO 'T' form."""
    if value is None:
        return None
    text = value.strip().replace(" ", "T", 1)
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise click.BadParameter(
            f"'{value}' is not a valid date/time. Use e.g. 2026-08-19 or 2026-08-19T10:00:00"
        )
    return value


def _sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _anomaly_cell(row: dict) -> str:
    if not row.get("is_anomaly"):
        return ""
    score = row.get("anomaly_score")
    return f"YES ({score:.2f})" if isinstance(score, (int, float)) else "YES"


def _print_rows(rows: List[dict], title: Optional[str] = None) -> None:
    """Show query results as a table (rich if installed, plain text otherwise)."""
    headers = ["id", "timestamp", "level", "source", "message", "anomaly"]
    data = [
        [str(r["id"]), r["timestamp"], r["level"], r["source"], r["message"], _anomaly_cell(r)]
        for r in rows
    ]
    if HAS_RICH:
        table = Table(title=title, show_lines=False)
        for h in headers:
            table.add_column(h, overflow="fold")
        styles = {"ERROR": "red", "CRITICAL": "bold red", "WARNING": "yellow"}
        for row, rec in zip(data, rows):
            style = styles.get(rec["level"])
            table.add_row(*row, style=style)
        Console(highlight=False).print(table)
        return
    if title:
        click.echo(title)
    widths = [max(len(h), *(len(row[i]) for row in data)) for i, h in enumerate(headers)]
    widths[4] = min(widths[4], 70)          # keep messages from wrapping the screen
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    click.echo(line)
    click.echo("  ".join("-" * w for w in widths))
    for row in data:
        cells = list(row)
        if len(cells[4]) > widths[4]:
            cells[4] = cells[4][: widths[4] - 3] + "..."
        click.echo("  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip())


class _LineParser:
    """Strict regex parser first, heuristic fallback second; tracks counts."""

    def __init__(self, track_timestamps: bool = True):
        self.strict = 0
        self.fallback = 0
        self.blank = 0
        self._last_ts: Optional[str] = None
        self._prev: Optional[dict] = None
        self._track = track_timestamps

    def __call__(self, line: str) -> Optional[dict]:
        record = parse_line(line)
        if record:
            self.strict += 1
        else:
            record = fallback_parse_line(line, default_timestamp=self._last_ts)
            if record is None:
                self.blank += 1
                return None
            self.fallback += 1
            # An indented line right after a parsed record (stack-trace frame,
            # wrapped message) belongs to that record: keep its level/source.
            if self._prev is not None and line[:1] in (" ", "\t"):
                record["level"] = self._prev["level"]
                record["source"] = self._prev["source"]
                record["timestamp"] = self._prev["timestamp"]
        self._prev = record
        if self._track:
            self._last_ts = record["timestamp"]
        return record


# ---------------------------------------------------------------------------
# command group
# ---------------------------------------------------------------------------
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name=None, version="1.0.0", prog_name="logsentry")
def cli():
    """LogSentry AI - ingest, search and monitor application logs."""


@cli.command("init-db")
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database file.")
def init_db_cmd(db):
    """Create the SQLite database and tables (safe to re-run)."""
    conn = _connect(db, create_schema=True)
    n = count_logs(conn)
    conn.close()
    click.echo(f"Database ready: {db} ({n} log rows)")


@cli.command(short_help="Read a log file, parse every line and store it.")
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database file.")
@click.option("--no-anomaly", is_flag=True, help="Skip the anomaly-detection step.")
@click.option("--contamination", type=click.FloatRange(0.001, 0.5), default=0.05, show_default=True,
              help="Expected share of anomalous lines (0.001 - 0.5).")
@click.option("--force", is_flag=True, help="Ingest even if this exact file was already ingested.")
def ingest(path, db, no_anomaly, contamination, force):
    """Read a log file (.log/.txt/.gz/.bz2/.xz/.zip), parse every line and store it."""
    if os.path.isdir(path):
        raise click.ClickException(f"'{path}' is a directory, not a log file.")
    if not os.path.isfile(path):
        raise click.ClickException(f"Log file not found: {path}")

    conn = _connect(db, create_schema=True)
    try:
        digest = _sha256_of(path)
    except OSError as exc:
        conn.close()
        raise click.ClickException(f"Cannot read {path}: {exc}")
    previous = find_ingested_file(conn, digest)
    if previous is not None and not force:
        conn.close()
        click.echo(f"Skipped: this exact file was already ingested "
                   f"({previous['row_count']} rows, {previous['ingested_at']} UTC, as {previous['path']}).")
        click.echo("Use --force to ingest it again.")
        return

    parser = _LineParser()
    stored_rows: List[dict] = []
    lines_read = 0
    try:
        for item in LogIngestor().read_lines(path):
            lines_read += 1
            record = parser(item["raw_line"])
            if record is None:
                continue
            row_id = insert_record(conn, record, commit=False)
            stored_rows.append(dict(record, id=row_id))
        record_ingested_file(conn, digest, path, len(stored_rows), commit=False)
        conn.commit()
    except (UnsupportedFileTypeError, ValueError, OSError, sqlite3.Error) as exc:
        conn.rollback()
        conn.close()
        raise click.ClickException(f"{exc}\nNothing was stored from this file.")

    flagged = 0
    if stored_rows and not no_anomaly:
        flagged = detect_and_store(conn, stored_rows, contamination=contamination)
    conn.close()

    click.echo(f"Ingested {path}")
    click.echo(f"  lines read          : {lines_read}")
    click.echo(f"  parsed (strict)     : {parser.strict}")
    click.echo(f"  parsed (fallback)   : {parser.fallback}")
    click.echo(f"  blank lines skipped : {parser.blank}")
    click.echo(f"  stored in database  : {len(stored_rows)}")
    if no_anomaly:
        click.echo("  anomalies flagged   : (skipped)")
    elif len(stored_rows) and flagged == 0:
        click.echo("  anomalies flagged   : 0 (need at least 10 lines for detection)"
                   if len(stored_rows) < 10 else "  anomalies flagged   : 0")
    else:
        click.echo(f"  anomalies flagged   : {flagged}")


@cli.command()
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database file.")
@click.option("--level", type=click.Choice(LEVEL_CHOICES, case_sensitive=False), help="Only this level.")
@click.option("--source", help="Only this exact source/component name.")
@click.option("--contains", help="Message must contain this text (case-insensitive).")
@click.option("--since", callback=_check_ts, help="From this time (inclusive), e.g. 2026-08-19T10:00:00.")
@click.option("--until", callback=_check_ts, help="Up to this time (inclusive); a bare date means the whole day.")
@click.option("--anomalies-only", is_flag=True, help="Only rows flagged as anomalies.")
@click.option("--limit", type=click.IntRange(1, MAX_LIMIT), default=100, show_default=True, help="Max rows.")
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True, help="Rows to skip (paging).")
@click.option("--order", type=click.Choice(["asc", "desc"], case_sensitive=False), default="desc",
              show_default=True, help="Sort by timestamp.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"], case_sensitive=False),
              default="table", show_default=True, help="Output format.")
def query(db, level, source, contains, since, until, anomalies_only, limit, offset, order, fmt):
    """Search stored logs with filters."""
    conn = _connect(db, must_exist=True)
    try:
        filters = dict(level=level, source=source, contains=contains, since=since,
                       until=until, anomalies_only=anomalies_only)
        rows = query_logs(conn, limit=limit, offset=offset, order=order.lower(), **filters)
        total = count_logs_matching(conn, **filters)
    except (ValueError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc))
    finally:
        conn.close()

    if fmt.lower() == "json":
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if not rows:
        click.echo("No matching logs." if total == 0 else
                   f"No rows at offset {offset} ({total} matching in total).")
        return
    _print_rows(rows)
    click.echo(f"Showing {len(rows)} of {total} matching log(s).")


@cli.command()
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database file.")
@click.option("--source", help="Limit the summary to one source.")
def stats(db, source):
    """Show a summary: totals, counts per level, anomalies, time range."""
    conn = _connect(db, must_exist=True)
    try:
        total = count_logs_matching(conn, source=source)
        anomalies = count_logs_matching(conn, source=source, anomalies_only=True)
        levels = count_by_level(conn, source=source)
        span = conn.execute(
            "SELECT MIN(timestamp) AS a, MAX(timestamp) AS b FROM logs"
            + (" WHERE source = ?" if source else ""),
            (source,) if source else (),
        ).fetchone()
        top = conn.execute(
            "SELECT source, COUNT(*) AS n FROM logs GROUP BY source ORDER BY n DESC, source LIMIT 5"
        ).fetchall()
    except sqlite3.Error as exc:
        raise click.ClickException(str(exc))
    finally:
        conn.close()

    click.echo(f"Database : {db}" + (f"  (source = {source})" if source else ""))
    click.echo(f"Total    : {total}")
    if total == 0:
        click.echo("(no logs stored yet - try: logsentry ingest <file>)")
        return
    click.echo(f"Anomalies: {anomalies}")
    click.echo(f"Range    : {span['a']}  ->  {span['b']}")
    click.echo("By level : " + ", ".join(f"{k}={v}" for k, v in levels.items()))
    if not source:
        click.echo("Top sources: " + ", ".join(f"{r['source']}={r['n']}" for r in top))


@cli.command(short_help="Live-watch a log file and raise alerts.")
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--db", default=None, help="Also store every parsed line in this SQLite file.")
@click.option("--threshold", type=click.IntRange(1), default=5, show_default=True,
              help="ERROR lines inside the window that trigger an alert.")
@click.option("--window", type=click.IntRange(1), default=300, show_default=True,
              help="Sliding window in seconds.")
@click.option("--keyword", "keywords", multiple=True,
              help="Extra text that triggers a CRITICAL alert (repeatable).")
@click.option("--from-start", is_flag=True, help="Read the existing content first (default: only new lines).")
@click.option("--no-follow", is_flag=True, help="Stop at end of file instead of waiting for new lines.")
@click.option("--poll-interval", type=click.FloatRange(0.05), default=0.5, show_default=True,
              help="Seconds between checks for new lines.")
def watch(path, db, threshold, window, keywords, from_start, no_follow, poll_interval):
    """Live-watch a log file (like tail -f) and raise alerts from the rules."""
    if os.path.isdir(path):
        raise click.ClickException(f"'{path}' is a directory, not a log file.")
    if not os.path.isfile(path):
        raise click.ClickException(f"Log file not found: {path}")
    for kw in keywords:
        if not kw.strip():
            raise click.BadParameter("keywords must not be empty", param_hint="--keyword")

    conn = _connect(db, create_schema=True) if db else None
    rules = [
        ThresholdRule(name="TooManyErrors", level="ERROR", threshold=threshold,
                      window_seconds=window, severity="HIGH"),
        PatternRule(name="DatabaseConnectionFailure", keyword="database connection failed",
                    severity="CRITICAL"),
        PatternRule(name="OutOfMemory", keyword="out of memory", severity="CRITICAL"),
    ]
    rules += [PatternRule(name=f"Keyword:{kw}", keyword=kw, severity="CRITICAL") for kw in keywords]
    engine = RulesEngine(rules=rules)

    parser = _LineParser(track_timestamps=False)
    state = {"lines": 0}

    def parse_and_store(line: str):
        record = parser(line)
        if record is None:
            return None
        state["lines"] += 1
        if conn is not None:
            try:
                insert_record(conn, record)
            except (ValueError, sqlite3.Error) as exc:
                click.echo(f"[!] could not store line: {exc}", err=True)
        return record

    monitor = LiveMonitor(engine=engine, parse_fn=parse_and_store)
    try:
        monitor.watch(path, follow=not no_follow, poll_interval=poll_interval, from_start=from_start)
    except (FileNotFoundError, OSError) as exc:
        raise click.ClickException(str(exc))
    finally:
        if conn is not None:
            conn.close()
    click.echo(f"Watch finished: {state['lines']} line(s) processed, "
               f"{len(engine.alert_history)} alert(s) raised.")


@cli.command()
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database file.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def clear(db, yes):
    """Delete every stored log row (the database file is kept)."""
    conn = _connect(db, must_exist=True)
    n = count_logs(conn)
    if not yes and not click.confirm(f"Delete all {n} rows from {db}?"):
        conn.close()
        click.echo("Cancelled.")
        return
    clear_logs(conn)
    conn.close()
    click.echo(f"Deleted {n} row(s).")


@cli.command()
@click.option("--keep", is_flag=True, help="Keep the temporary demo folder when finished.")
@click.pass_context
def demo(ctx, keep):
    """Run the full pipeline end-to-end on the bundled sample log."""
    if not SAMPLE_LOG.is_file():
        raise click.ClickException(f"Sample log missing: {SAMPLE_LOG}")
    work = tempfile.mkdtemp(prefix="logsentry_demo_")
    db = os.path.join(work, "demo.db")
    try:
        click.echo("== 1. init-db ==")
        ctx.invoke(init_db_cmd, db=db)
        click.echo("\n== 2. ingest sample log ==")
        ctx.invoke(ingest, path=str(SAMPLE_LOG), db=db, no_anomaly=False, contamination=0.05, force=False)
        click.echo("\n== 3. query: level ERROR ==")
        ctx.invoke(query, db=db, level="ERROR", source=None, contains=None, since=None, until=None,
                   anomalies_only=False, limit=100, offset=0, order="asc", fmt="table")
        click.echo("\n== 4. query: anomalies only ==")
        ctx.invoke(query, db=db, level=None, source=None, contains=None, since=None, until=None,
                   anomalies_only=True, limit=100, offset=0, order="asc", fmt="table")
        click.echo("\n== 5. stats ==")
        ctx.invoke(stats, db=db, source=None)
        click.echo("\n== 6. watch (replaying the sample log through the alert rules) ==")
        ctx.invoke(watch, path=str(SAMPLE_LOG), db=None, threshold=5, window=300, keywords=(),
                   from_start=True, no_follow=True, poll_interval=0.5)
        click.echo("\nDemo complete.")
    finally:
        if keep:
            click.echo(f"Demo files kept in: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main() -> None:  # entry point used by `pip install -e .`
    cli()


if __name__ == "__main__":
    main()
