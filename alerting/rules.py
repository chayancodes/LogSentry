"""
LogSentry — Alerting & Rules Engine (Member 4)
Defines Alert model and rule evaluation logic:
- ThresholdRule: counts matching log events within a sliding time window (e.g., >5 errors in 5 min)
- PatternRule: detects critical keywords in log messages (e.g., "database connection failed")
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Dict, Any


@dataclass
class Alert:
    """Represents an alert triggered by a rule."""
    rule_name: str
    timestamp: str          # Time the alert was produced
    severity: str           # "WARNING", "HIGH", or "CRITICAL"
    message: str           # Human-readable explanation of why the alert triggered
    record: Dict[str, Any]  # The parsed log record that triggered the alert


def _parse_iso_timestamp(ts_string: str) -> datetime:
    """Safely parse an ISO-8601 timestamp string into a consistent datetime object."""
    try:
        # Handles formats like "2026-08-19T10:02:01" or "2026-08-19T10:02:01+00:00"
        dt = datetime.fromisoformat(str(ts_string))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        # Fallback to current local time without tzinfo
        return datetime.now()


class Rule:
    """Base class for all alert rules."""

    def __init__(self, name: str, severity: str = "WARNING"):
        self.name = name
        self.severity = severity

    def evaluate(self, record: Dict[str, Any]) -> Optional[Alert]:
        """
        Evaluate a single parsed record against this rule.
        Returns an Alert if triggered, otherwise None.
        """
        raise NotImplementedError("Subclasses must implement evaluate()")


class ThresholdRule(Rule):
    """
    Triggers an alert if a specific condition occurs more than `threshold`
    times within a sliding window of `window_seconds`.
    
    Example: 5 ERROR logs within 300 seconds (5 minutes).
    """

    def __init__(
        self,
        name: str = "HighErrorRate",
        level: str = "ERROR",
        threshold: int = 5,
        window_seconds: int = 300,
        source: Optional[str] = None,
        severity: str = "HIGH",
        cooldown_seconds: int = 60,
    ):
        super().__init__(name=name, severity=severity)
        self.level = level.upper()
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.source = source
        self.cooldown_seconds = cooldown_seconds

        # Deque of timestamps for matching records
        self._history = deque()
        self._last_alert_time: Optional[datetime] = None

    def reset(self):
        """Reset internal history state (useful for tests or restarts)."""
        self._history.clear()
        self._last_alert_time = None

    def evaluate(self, record: Dict[str, Any]) -> Optional[Alert]:
        record_level = str(record.get("level", "")).upper()
        record_source = record.get("source")

        # Check if record matches level and optional source filter
        if record_level != self.level:
            return None

        if self.source is not None and record_source != self.source:
            return None

        current_time = _parse_iso_timestamp(record.get("timestamp", ""))

        # Evict timestamps outside the sliding window
        while self._history:
            oldest_time = self._history[0]
            try:
                diff_seconds = (current_time - oldest_time).total_seconds()
            except TypeError:
                diff_seconds = 0
            if diff_seconds > self.window_seconds:
                self._history.popleft()
            else:
                break

        # Add current event
        self._history.append(current_time)

        # Check if threshold is breached
        if len(self._history) >= self.threshold:
            # Check cooldown to avoid spamming alerts on every subsequent line
            if self._last_alert_time is not None:
                try:
                    time_since_alert = (current_time - self._last_alert_time).total_seconds()
                    if 0 <= time_since_alert < self.cooldown_seconds:
                        return None
                except TypeError:
                    pass

            self._last_alert_time = current_time
            return Alert(
                rule_name=self.name,
                timestamp=record.get("timestamp", datetime.now().isoformat()),
                severity=self.severity,
                message=(
                    f"Threshold breached: {len(self._history)} '{self.level}' logs "
                    f"occurred within {self.window_seconds}s (limit: {self.threshold})"
                ),
                record=record,
            )

        return None


class PatternRule(Rule):
    """
    Triggers an immediate alert if a log message contains a specific keyword
    or pattern (e.g. 'database connection failed', 'out of memory').
    """

    def __init__(
        self,
        name: str,
        keyword: str,
        severity: str = "CRITICAL",
        level: Optional[str] = None,
        source: Optional[str] = None,
        case_sensitive: bool = False,
    ):
        super().__init__(name=name, severity=severity)
        self.keyword = keyword if case_sensitive else keyword.lower()
        self.level = level.upper() if level else None
        self.source = source
        self.case_sensitive = case_sensitive

    def evaluate(self, record: Dict[str, Any]) -> Optional[Alert]:
        record_message = str(record.get("message", ""))
        record_level = str(record.get("level", "")).upper()
        record_source = record.get("source")

        # Check optional level filter
        if self.level is not None and record_level != self.level:
            return None

        # Check optional source filter
        if self.source is not None and record_source != self.source:
            return None

        # Check keyword match
        target_message = record_message if self.case_sensitive else record_message.lower()
        if self.keyword in target_message:
            return Alert(
                rule_name=self.name,
                timestamp=record.get("timestamp", datetime.now().isoformat()),
                severity=self.severity,
                message=f"Critical pattern detected: '{self.keyword}' found in message",
                record=record,
            )

        return None
