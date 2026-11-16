"""PII/secrets audit for agent-context-bridge (stdlib only, H2).

Scans ``records.jsonl`` line by line for common secret/PII patterns.
Findings never include the matched values — only type, count and line
numbers (values are masked as ``***`` at display time).
"""

import re
from pathlib import Path
from typing import Any, Dict, List

#: Pattern name -> compiled regex. Keys are stable identifiers used in
#: reports (both human and ``--json``). Values are never echoed.
AUDIT_PATTERNS: Dict[str, "re.Pattern[str]"] = {
    # OpenAI-style keys: sk-... (min 8 chars after prefix to limit noise).
    "openai_key": re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    # GitHub personal access tokens.
    "github_token": re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    # AWS access key IDs (AKIA + 16 uppercase alphanumerics).
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    # Slack tokens: xoxb-/xoxa-/xoxp-... (audit brief: xox[bap]).
    "slack_token": re.compile(r"xox[bap]-[A-Za-z0-9\-]{8,}"),
    # Email addresses (PII).
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    # PEM private keys (covers "BEGIN PRIVATE KEY" and variants like
    # "BEGIN RSA PRIVATE KEY").
    "private_key": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    # Private home paths (/home/... or /Users/...) — PII/system footprint.
    "private_path": re.compile(r"(?:/home/|/Users/)[\w.\-~/]+"),
}

#: Mask placeholder used in human output (values are never printed).
MASK = "***"


def scan_line(text: str) -> Dict[str, int]:
    """Return ``{pattern_name: occurrence_count}`` for one line ({} if clean)."""
    hits: Dict[str, int] = {}
    for name, rx in AUDIT_PATTERNS.items():
        try:
            matches = rx.findall(text)
        except re.error:
            continue
        if matches:
            hits[name] = len(matches)
    return hits


def audit_records_file(records_file: Path) -> Dict[str, Any]:
    """Scan a ``records.jsonl`` file; return a JSON-safe report (no values).

    Report shape::

        {
            "records": <non-empty lines scanned>,
            "total_findings": <total occurrences>,
            "counts": {<type>: <occurrences>},
            "findings": [{"line": N, "type": T, "count": C}, ...],
            "clean": <bool>,
        }
    """
    path = Path(records_file)
    counts: Dict[str, int] = {}
    findings: List[Dict[str, Any]] = []
    n_records = 0
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            if not raw.strip():
                continue
            n_records += 1
            for finding_type, count in scan_line(raw).items():
                counts[finding_type] = counts.get(finding_type, 0) + count
                findings.append({"line": lineno, "type": finding_type, "count": count})
    return {
        "records": n_records,
        "total_findings": sum(counts.values()),
        "counts": counts,
        "findings": findings,
        "clean": not findings,
    }


def audit_store(store: Any) -> Dict[str, Any]:
    """Scan ``store.records_file``; raise FileNotFoundError if uninitialized."""
    records_file = Path(store.records_file)
    if not records_file.exists():
        raise FileNotFoundError(
            f"ACB not initialized in {store.workspace} (run 'acb init')."
        )
    return audit_records_file(records_file)
