"""Tests for `acb audit` (AUDIT_SECURITY.md H2). Fake secrets only."""

import json
import subprocess
import sys
from pathlib import Path

from agent_context_bridge.audit import audit_store, scan_line
from agent_context_bridge.core import ContextRecord, MemoryStore

SRC_DIR = Path(__file__).parent.parent / "src"

FAKE_OPENAI = "sk-testFAKEKEY1234567890abcdef"
FAKE_GITHUB = "ghp_FAKEtesttoken1234567890"
FAKE_AWS = "AKIAIOSFODNN7EXAMPLE"
FAKE_SLACK = "xoxb-FAKEtesttoken123456"
FAKE_EMAIL = "dev-fake@example.com"
FAKE_PKEY = "-----BEGIN PRIVATE KEY-----"


def _run_cli(args, workspace: Path, stdin_text=None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(workspace), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True, input=stdin_text,
        env={"PYTHONPATH": str(SRC_DIR)}, timeout=30,
    )


def _seed_clean(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path)
    store.initialize()
    store.add_record(ContextRecord(
        agent="dev", topic="Architecture",
        summary="Adopted SQLite WAL mode.", details="No secrets here.",
    ))
    return store


def _seed_dirty(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path)
    store.initialize()
    store.add_record(ContextRecord(
        agent="dev", topic="Keys",
        summary="Rotated integration keys.",
        details=f"openai {FAKE_OPENAI} contact {FAKE_EMAIL}",
    ))
    return store


def test_scan_line_patterns_unit():
    assert scan_line("nothing secret here") == {}
    assert scan_line(f"key {FAKE_OPENAI}").get("openai_key") == 1
    assert scan_line(f"tok {FAKE_GITHUB}").get("github_token") == 1
    assert scan_line(f"aws {FAKE_AWS}").get("aws_key") == 1
    assert scan_line(f"slack {FAKE_SLACK}").get("slack_token") == 1
    assert scan_line(f"mail {FAKE_EMAIL}").get("email") == 1
    assert scan_line(f"pem {FAKE_PKEY}").get("private_key") == 1


def test_audit_clean_exit_zero(tmp_path: Path):
    _seed_clean(tmp_path)
    res = _run_cli(["audit"], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "No secrets/PII" in res.stdout


def test_audit_clean_json_exit_zero(tmp_path: Path):
    _seed_clean(tmp_path)
    res = _run_cli(["audit", "--json"], tmp_path)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["command"] == "audit"
    assert payload["clean"] is True
    assert payload["findings"] == []


def test_audit_dirty_exit_one_masks_values(tmp_path: Path):
    _seed_dirty(tmp_path)
    res = _run_cli(["audit"], tmp_path)
    assert res.returncode == 1
    combined = res.stdout + res.stderr
    # Finding types reported, values never printed (masked with ***).
    assert "openai_key" in combined or "email" in combined
    assert "***" in combined
    assert FAKE_OPENAI not in combined
    assert FAKE_EMAIL not in combined


def test_audit_dirty_json_masks_values(tmp_path: Path):
    _seed_dirty(tmp_path)
    res = _run_cli(["audit", "--json"], tmp_path)
    assert res.returncode == 1
    combined = res.stdout + res.stderr
    payload = json.loads(res.stdout)
    assert payload["clean"] is False
    assert payload["total_findings"] >= 2
    assert FAKE_OPENAI not in combined
    assert FAKE_EMAIL not in combined
    # Findings carry only line/type/count — no secret values.
    blob = json.dumps(payload)
    assert FAKE_OPENAI not in blob
    assert FAKE_EMAIL not in blob


def test_audit_store_api_masks_values(tmp_path: Path):
    store = _seed_dirty(tmp_path)
    report = audit_store(store)
    assert report["clean"] is False
    blob = json.dumps(report)
    assert FAKE_OPENAI not in blob
    assert FAKE_EMAIL not in blob


def test_audit_private_key_and_all_patterns(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    store.add_record(ContextRecord(
        agent="dev", topic="All patterns",
        summary="audit all",
        details=f"{FAKE_GITHUB} {FAKE_AWS} {FAKE_SLACK} {FAKE_PKEY}",
    ))
    report = audit_store(store)
    for expected in ("github_token", "aws_key", "slack_token", "private_key"):
        assert expected in report["counts"], report
    res = _run_cli(["audit"], tmp_path)
    assert res.returncode == 1
    combined = res.stdout + res.stderr
    for secret in (FAKE_GITHUB, FAKE_AWS, FAKE_SLACK):
        assert secret not in combined
