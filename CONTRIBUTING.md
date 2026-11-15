# Contributing

Thanks for your interest in `agent-context-bridge`!

## Quick start

```bash
git clone https://github.com/shenn667/agent-context-bridge.git
cd agent-context-bridge
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pytest -v
```

## Ground rules

- Python ≥ 3.10, stdlib only at runtime (no new dependencies without discussion).
- Offline-first: no network calls, no daemon, no telemetry.
- Every behavior change ships with a test (`pytest`).
- Every user-facing change updates `CHANGELOG.md` (Unreleased section) and `README.md` if needed.

## Pull requests

1. Fork, branch from `main` (`feat/<scope>`, `fix/<scope>`).
2. Keep PRs small and focused; describe the problem, the fix, and how you tested it.
3. `pytest -v` must be green. CI runs Python 3.10 / 3.11 / 3.12.

## Reporting issues

Include: ACB version (`acb export` header or `pip show`), Python version, OS,
minimal reproduction steps, and the content of `.agent_bridge/records.jsonl` (redacted if sensitive).
