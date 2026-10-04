"""
LogSentry — Ingestion Module
Owner: Member 1

Responsibility (and ONLY this):
    Open log files — plain text or compressed (.gz, .zip, .bz2, .xz) — and
    yield their raw lines, one at a time, along with basic source metadata.

This module does NOT:
    - Parse lines into the shared {timestamp, level, source, message} record
      (that's the Parser module's job).
    - Store anything (Storage module's job).
    - Watch files for live changes / tailing (Live Monitoring module's job).
    - Decide what's anomalous (AI/ML module's job).

Downstream modules should call `LogIngestor.read_lines(filepath)` and treat
its output (a generator of dicts) as their input.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import os
import zipfile
from typing import Iterator, TextIO


class UnsupportedFileTypeError(Exception):
    """Raised when the file extension/format isn't one we know how to read."""
    pass


class LogIngestor:
    """
    Reads raw lines out of a log file, transparently handling compression.

    Usage:
        ingestor = LogIngestor()
        for record in ingestor.read_lines("app.log.gz"):
            print(record)
            # {"source_file": "app.log.gz", "line_number": 1, "raw_line": "..."}
    """

    # Extensions we know how to decompress. Anything else is treated as
    # plain text (including .log, .txt, or no extension at all).
    SUPPORTED_COMPRESSED_EXTENSIONS = (".gz", ".bz2", ".xz", ".zip")

    def read_lines(self, filepath: str) -> Iterator[dict]:
        """
        Main entry point. Given a path to a log file (plain or compressed),
        yields one dict per line:

            {
                "source_file": <str, the filepath as given>,
                "line_number": <int, 1-indexed>,
                "raw_line": <str, the line with trailing newline stripped>
            }

        Raises:
            FileNotFoundError: if filepath does not exist.
            UnsupportedFileTypeError: if a .zip archive contains no readable
                files, or another format-specific problem occurs.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"No such file: {filepath}")

        line_number = 0
        with self._open(filepath) as file_handle:
            for raw_line in file_handle:
                line_number += 1
                yield {
                    "source_file": filepath,
                    "line_number": line_number,
                    "raw_line": raw_line.rstrip("\n").rstrip("\r"),
                }

    def _open(self, filepath: str) -> TextIO:
        """
        Returns a text-mode file handle for filepath, decompressing
        transparently based on file extension. Bad/garbled bytes are
        replaced rather than raising, so one corrupted line doesn't crash
        ingestion of an entire file.
        """
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".gz":
            return gzip.open(filepath, mode="rt", encoding="utf-8", errors="replace")

        if ext == ".bz2":
            return bz2.open(filepath, mode="rt", encoding="utf-8", errors="replace")

        if ext == ".xz":
            return lzma.open(filepath, mode="rt", encoding="utf-8", errors="replace")

        if ext == ".zip":
            return self._open_zip(filepath)

        # Default: treat as plain text.
        return open(filepath, mode="rt", encoding="utf-8", errors="replace")

    def _open_zip(self, filepath: str) -> TextIO:
        """
        Opens the first file inside a .zip archive as a text stream.
        Assumes one log file per archive, which is the common case for
        rotated/compressed logs (e.g. app.log.zip containing app.log).
        """
        zf = zipfile.ZipFile(filepath, mode="r")
        names = zf.namelist()
        if not names:
            zf.close()
            raise UnsupportedFileTypeError(f"Zip archive is empty: {filepath}")

        # If there are multiple files, just take the first one and note it.
        # (Multi-file archive support can be added later if the team needs it.)
        inner_name = names[0]
        inner_binary = zf.open(inner_name, mode="r")
        import io
        text_stream = io.TextIOWrapper(inner_binary, encoding="utf-8", errors="replace")

        # Keep a reference so the zip file isn't garbage-collected/closed early.
        text_stream._zipfile_ref = zf  # type: ignore[attr-defined]
        return text_stream
