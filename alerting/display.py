"""
Alert display and formatting for LogSentry.
Uses `rich` for terminal output formatting with fallback to standard print.
"""

import sys
from typing import Optional, Any
from .rules import Alert

try:
    from rich.console import Console
    from rich.panel import Panel

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    CONSOLE = None
    HAS_RICH = False


def format_alert_text(alert: Alert) -> str:
    """Format an alert as a clean, single-line text string."""
    source = alert.record.get("source", "unknown") if alert.record else "unknown"
    return (
        f"[{alert.severity}] [{alert.timestamp}] "
        f"Rule '{alert.rule_name}' triggered (source={source}): {alert.message}"
    )


def display_alert(alert: Alert, console: Optional[Any] = None) -> None:
    """
    Display a formatted alert to stdout/stderr.
    Uses rich Panel formatting when available, falling back to standard print.
    """
    active_console = console or CONSOLE

    if HAS_RICH and active_console is not None:
        severity_colors = {
            "CRITICAL": "bold red",
            "HIGH": "bold yellow",
            "WARNING": "yellow",
            "INFO": "cyan",
        }
        border_color = severity_colors.get(alert.severity.upper(), "red")

        content = (
            f"[bold]Timestamp:[/bold]  {alert.timestamp}\n"
            f"[bold]Severity:[/bold]   [{border_color}]{alert.severity}[/{border_color}]\n"
            f"[bold]Reason:[/bold]     {alert.message}\n"
        )

        if alert.record:
            source = alert.record.get("source", "N/A")
            level = alert.record.get("level", "N/A")
            raw_msg = alert.record.get("message", "")
            content += (
                f"[bold]Source:[/bold]     {source} (Level: {level})\n"
                f"[bold]Log Msg:[/bold]    {raw_msg}"
            )

        panel = Panel(
            content,
            title=f"[bold]ALERT: {alert.rule_name}[/bold]",
            border_style=border_color,
            expand=False,
        )
        try:
            active_console.print(panel)
        except UnicodeEncodeError:
            # Fallback if console character encoding (e.g. Windows cp1252) cannot display styling
            print(format_alert_text(alert), file=sys.stderr)
    else:
        # Fallback for standard console without rich
        text = format_alert_text(alert)
        print(f"[ALERT] {text}", file=sys.stderr)
