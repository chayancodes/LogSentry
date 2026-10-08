"""
Tests for LogSentry Alerting Module (Member 4).
Tests run directly against the shared parsed-record schema contract:
{
  "timestamp": "2026-08-19T10:02:01",
  "level": "INFO",
  "source": "scraper",
  "message": "fetched image_4471.jpg, size=1.2MB, dims=1024x768"
}

Run with:
    pytest alerting/test_alerting.py -v
"""

import time
import tempfile
import os
import pytest

from alerting import (
    RulesEngine,
    ThresholdRule,
    PatternRule,
    tail_file,
    LiveMonitor,
    display_alert,
    Alert,
)


def test_normal_record_does_not_trigger_alert():
    """A regular INFO log entry should produce zero alerts."""
    engine = RulesEngine()
    record = {
        "timestamp": "2026-08-19T10:02:01",
        "level": "INFO",
        "source": "scraper",
        "message": "fetched image_4471.jpg, size=1.2MB, dims=1024x768",
    }
    alerts = engine.process_record(record)
    assert alerts == []


def test_threshold_rule_triggers_when_limit_reached():
    """ThresholdRule should trigger an alert on the 5th ERROR within 5 minutes."""
    rule = ThresholdRule(
        name="ErrorBurst",
        level="ERROR",
        threshold=5,
        window_seconds=300,
        severity="HIGH",
    )
    engine = RulesEngine(rules=[rule])

    # Send 4 errors: should not trigger yet
    for i in range(1, 5):
        record = {
            "timestamp": f"2026-08-19T10:0{i}:00",
            "level": "ERROR",
            "source": "scraper",
            "message": f"Connection timeout #{i}",
        }
        alerts = engine.process_record(record)
        assert len(alerts) == 0, f"Unexpected alert on error #{i}"

    # 5th error: should trigger alert
    fifth_record = {
        "timestamp": "2026-08-19T10:05:00",
        "level": "ERROR",
        "source": "scraper",
        "message": "Connection timeout #5",
    }
    alerts = engine.process_record(fifth_record)
    assert len(alerts) == 1
    assert alerts[0].rule_name == "ErrorBurst"
    assert alerts[0].severity == "HIGH"
    assert "Threshold breached" in alerts[0].message
    assert alerts[0].record == fifth_record


def test_threshold_rule_ignores_expired_errors():
    """Errors that occur outside the time window should not accumulate."""
    rule = ThresholdRule(
        name="ErrorBurst",
        level="ERROR",
        threshold=3,
        window_seconds=60,  # 1 minute window
    )
    engine = RulesEngine(rules=[rule])

    # Error 1 at 10:00:00
    engine.process_record({
        "timestamp": "2026-08-19T10:00:00",
        "level": "ERROR",
        "source": "api",
        "message": "Error 1",
    })

    # Error 2 at 10:00:30 (30 seconds later)
    engine.process_record({
        "timestamp": "2026-08-19T10:00:30",
        "level": "ERROR",
        "source": "api",
        "message": "Error 2",
    })

    # Error 3 at 10:02:00 (90 seconds after Error 2, 120s after Error 1)
    # The first error has aged out of the 60s window, so count is only 2.
    alerts = engine.process_record({
        "timestamp": "2026-08-19T10:02:00",
        "level": "ERROR",
        "source": "api",
        "message": "Error 3",
    })
    assert len(alerts) == 0


def test_pattern_rule_detects_critical_message():
    """PatternRule should trigger immediately when a matching keyword is found."""
    rule = PatternRule(
        name="DatabasePanic",
        keyword="database connection failed",
        severity="CRITICAL",
    )
    engine = RulesEngine(rules=[rule])

    record = {
        "timestamp": "2026-08-19T10:15:30",
        "level": "ERROR",
        "source": "auth-service",
        "message": "Worker thread 4: Database connection failed after 3 retries",
    }

    alerts = engine.process_record(record)
    assert len(alerts) == 1
    assert alerts[0].rule_name == "DatabasePanic"
    assert alerts[0].severity == "CRITICAL"
    assert "Critical pattern detected" in alerts[0].message


def test_custom_on_alert_callback():
    """RulesEngine should call the on_alert callback when an alert is fired."""
    received_alerts = []

    def callback(alert):
        received_alerts.append(alert)

    rule = PatternRule(name="MemoryLeak", keyword="out of memory", severity="CRITICAL")
    engine = RulesEngine(rules=[rule], on_alert=callback)

    engine.process_record({
        "timestamp": "2026-08-19T10:20:00",
        "level": "WARNING",
        "source": "worker",
        "message": "Process aborted: Out of memory",
    })

    assert len(received_alerts) == 1
    assert received_alerts[0].rule_name == "MemoryLeak"


def test_tail_file_reads_appended_lines():
    """tail_file should read lines appended to a file in real-time."""
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
        filepath = f.name
        f.write("initial line 1\n")
        f.flush()

    try:
        # Read initial content
        stream = tail_file(filepath, follow=False, from_start=True)
        lines = list(stream)
        assert lines == ["initial line 1\n"]

        # Append new line
        with open(filepath, "a", encoding="utf-8") as f:
            f.write("appended line 2\n")

        stream2 = tail_file(filepath, follow=False, from_start=True)
        assert list(stream2) == ["initial line 1\n", "appended line 2\n"]

    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


def test_display_alert_runs_without_error():
    """Ensure display_alert formats and outputs an alert without throwing exceptions."""
    alert = Alert(
        rule_name="TestAlert",
        timestamp="2026-08-19T10:02:01",
        severity="HIGH",
        message="Test alert message",
        record={
            "timestamp": "2026-08-19T10:02:01",
            "level": "ERROR",
            "source": "test_src",
            "message": "Sample error log",
        },
    )
    display_alert(alert)


def test_live_monitor_processes_file():
    """LiveMonitor should read lines from a file and generate alerts via RulesEngine."""
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
        filepath = f.name
        f.write('{"timestamp": "2026-08-19T10:02:01", "level": "ERROR", "source": "db", "message": "database connection failed"}\n')
        f.flush()

    try:
        captured_alerts = []
        engine = RulesEngine(on_alert=lambda a: captured_alerts.append(a))
        monitor = LiveMonitor(engine=engine, auto_display=False)

        monitor.watch(filepath, follow=False, from_start=True)

        assert len(captured_alerts) == 1
        assert captured_alerts[0].rule_name == "DatabaseConnectionFailure"
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
