# LogSentry AI

**Intelligent Real-Time Log Monitoring, Anomaly Detection & Alerting**

LogSentry is a lightweight CLI tool that ingests, parses, stores, queries, and
monitors application log files in real time. It combines deterministic
rule-based checks with a small local ML model (scikit-learn `IsolationForest`)
to flag anomalous log entries — without needing heavyweight infrastructure
like Splunk or the ELK stack.

```
Log Files -> Ingestion -> Parser -> Storage (SQLite) -> Query Engine -> CLI Output
                              |
                    (unmatched lines) -> AI-Assisted Parser -> Alerting / Rules Engine
                                                                        ^
                                                            Live Tail / Watch Mode
```

## Why LogSentry

Most applications' logs are only reviewed manually after something has gone
wrong. LogSentry attaches lightweight, real-time anomaly detection to any
app's log stream, so error spikes and unfamiliar log patterns surface as
they happen, not after the fact.

## Project structure

```
logsentry/
  ingestion/    # Member 1 - read plain-text and .gz log files, line by line
  parser/       # Member 2 - regex parsing engine (+ optional C++ path)
  storage/      # Member 3 - SQLite schema, indexes, persistence
  query/        # Member 3 - translate filters into SQL queries
  alerting/     # Member 4 - rules engine + live "tail -f" style monitoring
  ai_parser/    # Member 5 - AI-assisted fallback parser + anomaly detection
  cli/          # wires every module together into one command-line tool
  tests/        # pytest suite (one file per module)
  data/         # sample log files used by tests and the demo command
```

Every module produces/consumes the same **parsed record** shape, which is the
one contract the whole team shares:

```json
{
  "timestamp": "2026-08-19T10:02:01",
  "level": "INFO",
  "source": "scraper",
  "message": "fetched image_4471.jpg, size=1.2MB, dims=1024x768"
}
```

## Five-member work division

| Member | Responsibility |
|---|---|
| 1 | Log ingestion + compressed-log handling |
| 2 | Parsing engine + regex processing + optional C++ performance module |
| 3 | SQLite storage + schema + indexes + query engine |
| 4 | Rules engine + live monitoring + alert generation |
| 5 | AI/ML adaptive parser + anomaly detection + testing/evaluation |

## Setup

Requires **Python 3.9+**.

```bash
git clone <this-repo-url>
cd logsentry
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
pip install -e .                                     # installs the `logsentry` CLI command
```

## Usage

```bash
# 1. Create the SQLite database (safe to re-run)
logsentry init-db --db logsentry.db

# 2. Ingest a log file (plain .txt/.log or gzip .gz) - parses every line and stores it
logsentry ingest logsentry/data/sample.log --db logsentry.db

# 3. Query stored logs
logsentry query --db logsentry.db --level ERROR
logsentry query --db logsentry.db --source scraper --contains "size="
logsentry query --db logsentry.db --anomalies-only

# 4. Live-watch a growing log file (like `tail -f`) with rule-based alerting
logsentry watch /var/log/myapp.log --db logsentry.db --threshold 5 --window 300

# 5. Run the full exhibition demo end-to-end
logsentry demo
```

If you didn't `pip install -e .`, replace `logsentry` above with
`python -m logsentry.cli.main`.

### Sample output

```
$ logsentry query --db logsentry.db --level ERROR
┌────┬─────────────────────┬───────┬────────┬──────────────────────────────────┬─────────┐
│ id │ timestamp           │ level │ source │ message                          │ anomaly │
├────┼─────────────────────┼───────┼────────┼──────────────────────────────────┼─────────┤
│ 7  │ 2026-08-19T10:00:31 │ ERROR │ db     │ connection timeout after 3000ms  │         │
│ 8  │ 2026-08-19T10:00:33 │ ERROR │ db     │ connection timeout after 3000ms  │         │
│ 9  │ 2026-08-19T10:00:35 │ ERROR │ db     │ connection timeout after 3000ms  │         │
└────┴─────────────────────┴───────┴────────┴──────────────────────────────────┴─────────┘
```

## Running the tests

```bash
pytest logsentry/tests -v
```

The suite covers every module independently (ingestion, parser, storage,
query, alerting rules, the AI-assisted parser + anomaly detector) plus a
handful of end-to-end CLI tests.

## Continuous Integration

`.github/workflows/ci.yml` runs the full test suite on Python 3.10 and 3.11
on every push and pull request to `main`, and smoke-tests the CLI's
`init-db` -> `ingest` -> `query` flow.

## Technology stack

| Purpose | Tool |
|---|---|
| Core application | Python |
| CLI | Click |
| Terminal output | Rich |
| Storage | SQLite (`sqlite3`) |
| AI / anomaly detection | scikit-learn (`IsolationForest`) |
| Performance path (optional) | C++ (`logsentry/parser/cpp`) |
| Testing | pytest |
| CI | GitHub Actions |

## Optional C++ performance path

`logsentry/parser/cpp/parser.cpp` reimplements the ISO-timestamp regex
parser in C++ as a stretch goal, so the team can benchmark it against the
Python version. See `logsentry/parser/cpp/README.md` for build/run
instructions. This is a bonus — the pipeline works end-to-end using only
the Python parser.

## Ethics & scope notes

- Logs can contain operationally sensitive information; LogSentry doesn't
  expose more fields than necessary in alerts and is intended for
  legitimate system-monitoring use.
- LogSentry is a monitoring **aid** — alerts still require human/system
  validation before any consequential action is taken.
- The AI component is intentionally lightweight (scikit-learn
  `IsolationForest`), not a deep-learning model, and storage is a single
  local SQLite file rather than a heavier database or blockchain — matching
  the project's stated scope.

## Future scope

Web dashboard, centralized multi-server monitoring, stronger anomaly
detection models, alert integrations (Slack/email), security
visualizations, and cloud deployment.

## Team 49

Sousthab Mitra-25BCE10480
Aranyak Sarma-25BCE10994
Chayan Mukherjee-25BCE10620
Suraj Gorakshanath Pisal-25BCE10377
Priyanshu Patil-25BCE10192

## License

MIT — see [LICENSE](LICENSE).
