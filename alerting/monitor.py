"""
Live monitoring and file-tailing module for LogSentry (Member 4).
Watches log files in real-time (similar to `tail -f`), parses new lines,
and passes parsed records into the RulesEngine.
"""

import os
import time
import json
import re
from typing import Generator, Callable, Optional, Dict, Any
from .engine import RulesEngine
from .display import display_alert

# Attempt to hook into Member 2's parser if available
_default_teammate_parser = None
try:
    from parser.parser import parse_line as _default_teammate_parser
except ImportError:
    try:
        from logsentry.parser.parser import parse_line as _default_teammate_parser
    except ImportError:
        pass


def _fallback_parse_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Fallback parser used if Member 2's parser isn't provided.
    Handles JSON lines, standard bracketed logs, and generic text.
    """
    stripped = line.strip()
    if not stripped:
        return None

    # Check if line is JSON
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "level" in data and "message" in data:
                return {
                    "timestamp": data.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S")),
                    "level": data.get("level", "INFO"),
                    "source": data.get("source", "system"),
                    "message": data.get("message", ""),
                }
        except json.JSONDecodeError:
            pass

    # Regex for standard format: [2026-08-19T10:02:01] [ERROR] [scraper] message...
    pattern = r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<lvl>[^\]]+)\]\s+\[(?P<src>[^\]]+)\]\s+(?P<msg>.*)$"
    match = re.match(pattern, stripped)
    if match:
        return {
            "timestamp": match.group("ts"),
            "level": match.group("lvl"),
            "source": match.group("src"),
            "message": match.group("msg"),
        }

    # Fallback structure matching the contract
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "level": "INFO",
        "source": "unknown",
        "message": stripped,
    }


def tail_file(
    filepath: str,
    follow: bool = True,
    poll_interval: float = 0.5,
    from_start: bool = False,
) -> Generator[str, None, None]:
    """
    Generator that monitors a file and yields new lines as they are appended
    (equivalent to `tail -f`).
    
    :param filepath: Path to the log file to monitor.
    :param follow: If True, keep polling for new lines indefinitely.
    :param poll_interval: Sleep time (in seconds) between file checks when idle.
    :param from_start: If False, start at EOF; if True, read from beginning.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Log file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        if not from_start:
            # Jump to end of file to only watch new additions
            f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()
            if line:
                yield line
            else:
                if not follow:
                    break

                time.sleep(poll_interval)

                # Check if file was rotated or truncated
                try:
                    current_size = os.path.getsize(filepath)
                    if current_size < f.tell():
                        f.seek(0, os.SEEK_SET)
                except OSError:
                    pass


def _smart_parse(line: str) -> Optional[Dict[str, Any]]:
    """Parse using Member 2's parser if available, falling back if line unmatched."""
    if _default_teammate_parser is not None:
        try:
            record = _default_teammate_parser(line)
            if record:
                return record
        except Exception:
            pass
    return _fallback_parse_line(line)


class LiveMonitor:
    """
    Coordinates live file watching with the RulesEngine and log parsing.
    """

    def __init__(
        self,
        engine: Optional[RulesEngine] = None,
        parse_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        auto_display: bool = True,
    ):
        """
        :param engine: RulesEngine instance (creates default engine if None).
        :param parse_fn: Function to parse raw line into standard record dict.
                         Defaults to smart parser combining Member 2's parser and fallback.
        :param auto_display: If True, prints formatted alerts using display_alert.
        """
        self.engine = engine or RulesEngine()
        self.parse_fn = parse_fn or _smart_parse
        self.auto_display = auto_display
        self._running = False

    def stop(self) -> None:
        """Signal the monitor loop to stop."""
        self._running = False

    def watch(
        self,
        filepath: str,
        follow: bool = True,
        poll_interval: float = 0.5,
        from_start: bool = False,
    ):
        """
        Start watching a log file in real time.
        Reads lines as they are appended, parses them, and checks rules.
        """
        self._running = True
        print(f"[*] LogSentry LiveMonitor active on: {filepath} (Press Ctrl+C to stop)")

        try:
            for line in tail_file(
                filepath,
                follow=follow,
                poll_interval=poll_interval,
                from_start=from_start,
            ):
                if not self._running:
                    break

                record = self.parse_fn(line)
                if not record:
                    continue

                alerts = self.engine.process_record(record)
                if alerts and self.auto_display:
                    for alert in alerts:
                        display_alert(alert)

        except KeyboardInterrupt:
            print("\n[*] Live monitoring stopped by user.")
        finally:
            self._running = False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m alerting.monitor <log_filepath> [--from-start]")
        print("Example: python -m alerting.monitor app.log")
        sys.exit(1)

    log_path = sys.argv[1]
    read_from_start = "--from-start" in sys.argv

    if not os.path.exists(log_path):
        print(f"Creating empty file for live watching: {log_path}")
        with open(log_path, "w", encoding="utf-8") as f:
            pass

    monitor = LiveMonitor()
    monitor.watch(log_path, follow=True, from_start=read_from_start)

