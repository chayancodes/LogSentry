"""Tests for Member 3's query engine (logsentry.query.query_engine)."""

import pytest

from logsentry.storage import insert_many, mark_anomalies
from logsentry.query import query_logs, count_by_level, count_logs_matching


def _seed(db_conn, sample_records):
    insert_many(db_conn, sample_records)


def test_query_with_no_filters_returns_everything(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, limit=100)
    assert len(rows) == len(sample_records)


def test_filter_by_level(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, level="ERROR", limit=100)
    assert len(rows) == 3
    assert all(r["level"] == "ERROR" for r in rows)


def test_filter_by_source(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, source="scraper", limit=100)
    assert len(rows) == 2
    assert all(r["source"] == "scraper" for r in rows)


def test_filter_by_contains_is_case_insensitive(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, contains="TIMEOUT", limit=100)
    assert len(rows) == 3


def test_filter_by_time_range(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, since="2026-08-19T10:00:10", until="2026-08-19T10:00:20", limit=100)
    timestamps = {r["timestamp"] for r in rows}
    assert timestamps == {"2026-08-19T10:00:10", "2026-08-19T10:00:15", "2026-08-19T10:00:20"}


def test_combined_filters(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, level="ERROR", source="db", limit=100)
    assert len(rows) == 3


def test_limit_caps_results(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, limit=2)
    assert len(rows) == 2


def test_count_by_level_summary(db_conn, sample_records):
    _seed(db_conn, sample_records)
    summary = count_by_level(db_conn)
    assert summary == {"ERROR": 3, "INFO": 2, "WARNING": 1}


def test_contains_treats_percent_and_underscore_literally(db_conn):
    base = {"level": "INFO", "source": "a"}
    insert_many(db_conn, [
        dict(base, timestamp="2026-08-19T10:00:00", message="disk 100% full"),
        dict(base, timestamp="2026-08-19T10:00:01", message="disk 100 used"),
        dict(base, timestamp="2026-08-19T10:00:02", message="file_a ok"),
        dict(base, timestamp="2026-08-19T10:00:03", message="fileXa ok"),
    ])
    assert len(query_logs(db_conn, contains="%")) == 1
    assert len(query_logs(db_conn, contains="file_a")) == 1


def test_level_filter_is_case_insensitive(db_conn, sample_records):
    _seed(db_conn, sample_records)
    assert len(query_logs(db_conn, level="error")) == 3


def test_since_accepts_space_separated_timestamp(db_conn, sample_records):
    _seed(db_conn, sample_records)
    rows = query_logs(db_conn, since="2026-08-19 10:00:20")
    assert {r["timestamp"] for r in rows} == {"2026-08-19T10:00:20", "2026-08-19T10:00:25"}


def test_order_asc_and_desc(db_conn, sample_records):
    _seed(db_conn, sample_records)
    asc = [r["timestamp"] for r in query_logs(db_conn, order="asc")]
    desc = [r["timestamp"] for r in query_logs(db_conn, order="desc")]
    assert asc == sorted(asc) and desc == sorted(desc, reverse=True)


def test_offset_pages_without_overlap(db_conn, sample_records):
    _seed(db_conn, sample_records)
    p1 = query_logs(db_conn, limit=2, offset=0)
    p2 = query_logs(db_conn, limit=2, offset=2)
    assert not {r["id"] for r in p1} & {r["id"] for r in p2}


def test_equal_timestamps_have_stable_order(db_conn):
    rec = {"timestamp": "2026-08-19T10:00:00", "level": "INFO", "source": "s"}
    insert_many(db_conn, [dict(rec, message=f"m{i}") for i in range(5)])
    ids = [r["id"] for r in query_logs(db_conn, order="asc")]
    assert ids == sorted(ids)


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": -1}, {"order": "sideways"}, {"offset": -3}])
def test_invalid_arguments_raise(db_conn, kwargs):
    with pytest.raises(ValueError):
        query_logs(db_conn, **kwargs)


def test_anomalies_only_returns_flagged_rows(db_conn, sample_records):
    _seed(db_conn, sample_records)
    assert query_logs(db_conn, anomalies_only=True) == []
    mark_anomalies(db_conn, [(4, True, -0.9)])
    rows = query_logs(db_conn, anomalies_only=True)
    assert [r["id"] for r in rows] == [4] and rows[0]["anomaly_score"] == -0.9


def test_count_logs_matching_ignores_limit(db_conn, sample_records):
    _seed(db_conn, sample_records)
    assert count_logs_matching(db_conn, level="ERROR") == 3


def test_count_by_level_respects_source_filter(db_conn, sample_records):
    _seed(db_conn, sample_records)
    assert count_by_level(db_conn, source="db") == {"ERROR": 3}


def test_empty_database_returns_empty(db_conn):
    assert query_logs(db_conn) == []
    assert count_by_level(db_conn) == {}
