"""
LogSentry : Parsing Module 

Directive:
Converts raw log lines into structured records.

Output shape (the "parsed record"):
{
    "timestamp": "2026-08-19T10:02:01",
    "level": "INFO",           INFO / WARNING / WARN / ERROR / DEBUG
    "source": "scraper",
    "message": "fetched image_4471.jpg, size=1.2MB"
}
"""

import re

# Pattern 1: generic app-style logs
# e.g. 2026-08-19T10:02:01 INFO scraper: fetched image_4471.jpg, size=1.2MB
GENERIC_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>INFO|WARN|WARNING|ERROR|DEBUG)\s+"
    r"(?P<source>[\w\-]+):\s+"
    r"(?P<message>.+)$"
)

# Pattern 2: Apache/Nginx-style access logs (stretch — fill in later)
# e.g. 127.0.0.1 - - [19/Aug/2026:10:02:01] "GET /index.html HTTP/1.1" 200
ACCESS_LOG_PATTERN = re.compile(
    r'^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+'
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<request>[^"]+)"\s+(?P<status>\d+)'
)


def parse_line(line: str) -> dict | None:
    """
    Parse a single raw log line into a structured record.

    Returns:
        dict matching the parsed-record schema, or None if the line
        doesn't match any known format (caller should hand it to the
        AI-assisted parser in that case).
    """
    line = line.strip()
    if not line:
        return None

    match = GENERIC_PATTERN.match(line)
    if match:
        data = match.groupdict()
        # normalize WARN -> WARNING for consistency
        if data["level"] == "WARN":
            data["level"] = "WARNING"
        return data

    match = ACCESS_LOG_PATTERN.match(line)
    if match:
        data = match.groupdict()
        return {
            "timestamp": data["timestamp"],
            "level": "INFO" if data["status"].startswith("2") else "ERROR",
            "source": "access_log",
            "message": f'{data["request"]} status={data["status"]}',
        }

    # Didn't match anything known
    return None


if __name__ == "__main__":
    # quick manual smoke test
    sample_lines = [
        '2026-08-19T10:02:01 INFO scraper: fetched image_4471.jpg, size=1.2MB',
        '2026-08-19T10:04:11 WARN scraper: fetched image_4502.jpg, size=0.02MB',
        'this is not a valid log line at all',
    ]
    for line in sample_lines:
        print(parse_line(line))
