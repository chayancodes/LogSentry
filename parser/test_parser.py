"""
Test cases for parser.py — write these BEFORE touching C++.
If your C++ port produces the same output on the same inputs, the port is correct.
"""

from parser import parse_line


def test_valid_info_line():
    result = parse_line('2026-08-19T10:02:01 INFO scraper: fetched image_4471.jpg, size=1.2MB')
    assert result == {
        "timestamp": "2026-08-19T10:02:01",
        "level": "INFO",
        "source": "scraper",
        "message": "fetched image_4471.jpg, size=1.2MB",
    }


def test_warn_normalizes_to_warning():
    result = parse_line('2026-08-19T10:04:11 WARN scraper: fetched image_4502.jpg, size=0.02MB')
    assert result["level"] == "WARNING"


def test_error_line():
    result = parse_line('2026-08-19T10:06:02 ERROR trainer: BLOCKED image_4504.html from batch 12')
    assert result["level"] == "ERROR"
    assert result["source"] == "trainer"


def test_unmatched_line_returns_none():
    result = parse_line('this is not a valid log line at all')
    assert result is None


def test_empty_line_returns_none():
    assert parse_line('') is None
    assert parse_line('   ') is None


def test_access_log_format():
    result = parse_line('127.0.0.1 - - [19/Aug/2026:10:02:01] "GET /index.html HTTP/1.1" 200')
    assert result["level"] == "INFO"
    assert "GET /index.html" in result["message"]
