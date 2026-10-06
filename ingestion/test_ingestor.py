"""
Tests for LogSentry Ingestion Module (Member 1).

Run with:  pytest tests/test_ingestor.py -v
"""

import bz2
import gzip
import lzma
import zipfile

import pytest

from ingestion.ingestor import LogIngestor, UnsupportedFileTypeError

SAMPLE_LINES = [
    "2026-08-19T10:02:01 INFO scraper fetched image_4471.jpg, size=1.2MB",
    "2026-08-19T10:02:03 ERROR scraper failed to fetch image_4472.jpg",
    "2026-08-19T10:02:05 WARNING scraper retrying image_4472.jpg",
]
SAMPLE_CONTENT = "\n".join(SAMPLE_LINES) + "\n"


@pytest.fixture
def ingestor():
    return LogIngestor()


def _expected_records(filepath):
    return [
        {"source_file": filepath, "line_number": i + 1, "raw_line": line}
        for i, line in enumerate(SAMPLE_LINES)
    ]


# --- Test 1: plain text file ---
def test_reads_plain_text_file(tmp_path, ingestor):
    filepath = tmp_path / "app.log"
    filepath.write_text(SAMPLE_CONTENT)

    result = list(ingestor.read_lines(str(filepath)))

    assert result == _expected_records(str(filepath))


# --- Test 2: gzip-compressed file ---
def test_reads_gzip_file(tmp_path, ingestor):
    filepath = tmp_path / "app.log.gz"
    with gzip.open(filepath, "wt") as f:
        f.write(SAMPLE_CONTENT)

    result = list(ingestor.read_lines(str(filepath)))

    assert result == _expected_records(str(filepath))


# --- Test 3: zip-compressed file ---
def test_reads_zip_file(tmp_path, ingestor):
    filepath = tmp_path / "app.log.zip"
    with zipfile.ZipFile(filepath, "w") as zf:
        zf.writestr("app.log", SAMPLE_CONTENT)

    result = list(ingestor.read_lines(str(filepath)))

    assert result == _expected_records(str(filepath))


# --- Test 4: bz2 and xz compressed files ---
def test_reads_bz2_file(tmp_path, ingestor):
    filepath = tmp_path / "app.log.bz2"
    with bz2.open(filepath, "wt") as f:
        f.write(SAMPLE_CONTENT)

    result = list(ingestor.read_lines(str(filepath)))

    assert result == _expected_records(str(filepath))


def test_reads_xz_file(tmp_path, ingestor):
    filepath = tmp_path / "app.log.xz"
    with lzma.open(filepath, "wt") as f:
        f.write(SAMPLE_CONTENT)

    result = list(ingestor.read_lines(str(filepath)))

    assert result == _expected_records(str(filepath))


# --- Test 5: missing file raises FileNotFoundError ---
def test_missing_file_raises(tmp_path, ingestor):
    missing_path = tmp_path / "does_not_exist.log"

    with pytest.raises(FileNotFoundError):
        list(ingestor.read_lines(str(missing_path)))


# --- Test 6: empty file yields no records (not an error) ---
def test_empty_file_yields_nothing(tmp_path, ingestor):
    filepath = tmp_path / "empty.log"
    filepath.write_text("")

    result = list(ingestor.read_lines(str(filepath)))

    assert result == []


# --- Test 7: corrupted/garbled bytes don't crash ingestion ---
def test_corrupted_bytes_do_not_crash(tmp_path, ingestor):
    filepath = tmp_path / "corrupted.log"
    filepath.write_bytes(
        b"2026-08-19T10:00:00 INFO scraper valid line\n"
        b"2026-08-19T10:00:01 INFO scraper bad byte \xff\xfe here\n"
    )

    result = list(ingestor.read_lines(str(filepath)))

    assert len(result) == 2
    assert result[0]["raw_line"] == "2026-08-19T10:00:00 INFO scraper valid line"
    # second line should not crash; garbled bytes get replaced, not raised
    assert "bad byte" in result[1]["raw_line"]


# --- Test 8: empty zip archive raises a clear error ---
def test_empty_zip_raises_unsupported_error(tmp_path, ingestor):
    filepath = tmp_path / "empty.zip"
    with zipfile.ZipFile(filepath, "w"):
        pass  # zip with no entries

    with pytest.raises(UnsupportedFileTypeError):
        list(ingestor.read_lines(str(filepath)))
