"""
RulesEngine for LogSentry (Member 4).
Main entry point for processing parsed log records against active rules.
"""

from typing import List, Dict, Any, Optional, Callable, Iterable
from .rules import Rule, Alert, ThresholdRule, PatternRule


class RulesEngine:
    """
    Central engine for evaluating parsed records against configured rules.
    
    This is the primary interface for Member 4:
        engine = RulesEngine()
        alerts = engine.process_record(parsed_record)
    """

    def __init__(
        self,
        rules: Optional[List[Rule]] = None,
        on_alert: Optional[Callable[[Alert], None]] = None,
    ):
        """
        Initialize the RulesEngine.
        
        :param rules: Custom list of Rule instances. If None, default rules are used.
        :param on_alert: Optional callback function invoked immediately when an alert triggers.
        """
        if rules is not None:
            self.rules: List[Rule] = list(rules)
        else:
            self.rules: List[Rule] = self.get_default_rules()

        self.on_alert = on_alert
        self.alert_history: List[Alert] = []

    @staticmethod
    def get_default_rules() -> List[Rule]:
        """Provide sensible default rules for out-of-the-box monitoring."""
        return [
            ThresholdRule(
                name="TooManyErrors",
                level="ERROR",
                threshold=5,
                window_seconds=300,
                severity="HIGH",
            ),
            PatternRule(
                name="DatabaseConnectionFailure",
                keyword="database connection failed",
                severity="CRITICAL",
            ),
            PatternRule(
                name="OutOfMemory",
                keyword="out of memory",
                severity="CRITICAL",
            ),
        ]

    def add_rule(self, rule: Rule) -> None:
        """Add a new rule to the engine."""
        self.rules.append(rule)

    def remove_rule(self, rule_name: str) -> None:
        """Remove a rule by name."""
        self.rules = [r for r in self.rules if r.name != rule_name]

    def reset(self) -> None:
        """Reset internal history for all stateful rules and clear alert history."""
        self.alert_history.clear()
        for rule in self.rules:
            if hasattr(rule, "reset") and callable(getattr(rule, "reset")):
                rule.reset()

    def process_record(self, record: Dict[str, Any]) -> List[Alert]:
        """
        Process a single parsed record against all rules.
        
        Record must match the shared contract:
        {
            "timestamp": "2026-08-19T10:02:01",
            "level": "INFO",
            "source": "scraper",
            "message": "..."
        }
        
        :param record: The parsed log record dict.
        :return: List of Alert objects generated for this record (empty if none triggered).
        """
        triggered_alerts: List[Alert] = []

        for rule in self.rules:
            alert = rule.evaluate(record)
            if alert:
                triggered_alerts.append(alert)
                self.alert_history.append(alert)

                # Invoke callback if configured
                if self.on_alert:
                    try:
                        self.on_alert(alert)
                    except Exception as e:
                        print(f"[RulesEngine Warning] on_alert callback failed: {e}")

        return triggered_alerts

    def process_stream(self, records: Iterable[Dict[str, Any]]):
        """
        Generator that processes an iterable or stream of parsed records
        and yields alerts as they occur.
        """
        for record in records:
            for alert in self.process_record(record):
                yield alert
