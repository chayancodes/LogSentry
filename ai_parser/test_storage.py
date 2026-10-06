"""Tests for Member 3's storage module (logsentry.storage.db)."""

import pytest

from logsentry.storage import (
    insert_record, insert_many, mark_anomalies, count_logs, clear_logs, get_connection, init_db,
)


def test_init_db_creates_logs_table(db_conn):
    tables = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='logs'"
    ).fetchall()
    assert len(tables) == 1


def test_insert_record_returns_new_id(db_conn, sample_records):
    row_id = insert_record(db_conn, sample_records[0])
    assert row_id == 1


def test_inserted_record_is_retrievable(db_conn, sample_records):
    insert_record(db_conn, sample_records[0])
    row = db_conn.execute("SELECT * FROM logs WHERE id = 1").fetchone()
    assert row["timestamp"] == sample_records[0]["timestamp"]
    assert row["level"] == sample_records[0]["level"]
    assert row["source"] == sample_records[0]["source"]
    assert row["message"] == sample_records[0]["message"]
    assert row["is_anomaly"] == 0


def test_insert_record_can_mark_anomaly(db_conn, sample_records):
    insert_record(db_conn, sample_records[0], is_anomaly=True, anomaly_score=-0.42)
    row = db_conn.execute("SELECT * FROM logs WHERE id = 1").fetchone()
    assert row["is_anomaly"] == 1
    assert row["anomaly_score"] == -0.42


def test_insert_many_inserts_all_records(db_conn, sample_records):
    count = insert_many(db_conn, sample_records)
    assert count == len(sample_records)
    total = db_conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"]
    assert total == len(sample_records)


def test_clear_logs_removes_all_rows(db_conn, sample_records):
    insert_many(db_conn, sample_records)
    clear_logs(db_conn)
    total = db_conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"]
    assert total == 0


def test_init_db_is_idempotent(db_conn):
    init_db(db_conn)
    init_db(db_conn)
    assert count_logs(db_conn) == 0


def test_composite_and_partial_indexes_exist(db_conn):
    names = {r["name"] for r in db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_logs_level_ts", "idx_logs_source_ts", "idx_logs_anomaly_ts"} <= names


def test_level_is_normalised_to_uppercase(db_conn, sample_records):
    rec = dict(sample_records[0], level="error")
    insert_record(db_conn, rec)
    assert db_conn.execute("SELECT level FROM logs").fetchone()["level"] == "ERROR"


@pytest.mark.parametrize("missing", ["timestamp", "level", "source", "message"])
def test_insert_record_rejects_missing_field(db_conn, sample_records, missing):
    rec = dict(sample_records[0])
    rec.pop(missing)
    with pytest.raises(ValueError):
        insert_record(db_conn, rec)
    assert count_logs(db_conn) == 0


def test_insert_many_is_all_or_nothing(db_conn, sample_records):
    bad = sample_records[:2] + [{"timestamp": "t", "level": "INFO", "source": "s"}]
    with pytest.raises(ValueError):
        insert_many(db_conn, bad)
    assert count_logs(db_conn) == 0


def test_insert_many_keeps_anomaly_fields(db_conn, sample_records):
    recs = [dict(sample_records[0], is_anomaly=True, anomaly_score=-0.7), sample_records[1]]
    insert_many(db_conn, recs)
    rows = db_conn.execute("SELECT is_anomaly, anomaly_score FROM logs ORDER BY id").fetchall()
    assert (rows[0]["is_anomaly"], rows[0]["anomaly_score"]) == (1, -0.7)
    assert (rows[1]["is_anomaly"], rows[1]["anomaly_score"]) == (0, None)


def test_insert_record_without_commit_batches(db_conn, sample_records):
    for rec in sample_records:
        insert_record(db_conn, rec, commit=False)
    db_conn.commit()
    assert count_logs(db_conn) == len(sample_records)


def test_mark_anomalies_updates_existing_rows(db_conn, sample_records):
    insert_many(db_conn, sample_records)
    updated = mark_anomalies(db_conn, [(4, True, -0.5), (5, True, -0.6)])
    assert updated == 2
    flagged = [r["id"] for r in db_conn.execute("SELECT id FROM logs WHERE is_anomaly = 1")]
    assert sorted(flagged) == [4, 5]


def test_get_connection_creates_parent_folder(tmp_path):
    conn = get_connection(tmp_path / "nested" / "dir" / "x.db")
    init_db(conn)
    assert (tmp_path / "nested" / "dir" / "x.db").exists()
