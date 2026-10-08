"""
LogSentry — Alerting & Rules Engine Module
Owner: Member 4

Responsibilities:
- Rules engine with sliding-window threshold checks & keyword pattern detection
- Live log tailing ('tail -f' style monitoring)
- Terminal alert generation & Rich formatting
"""

from .rules import Alert, Rule, ThresholdRule, PatternRule
from .engine import RulesEngine
from .monitor import LiveMonitor, tail_file
from .display import display_alert, format_alert_text

__all__ = [
    "Alert",
    "Rule",
    "ThresholdRule",
    "PatternRule",
    "RulesEngine",
    "LiveMonitor",
    "tail_file",
    "display_alert",
    "format_alert_text",
]
