"""Tests for AUDIT_SECURITY.md fixes: M1 perms + H2 record warning. Fake secrets only."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from agent_context_bridge.core import ContextRecord, MemoryStore

SRC_DIR = Path(__file__).parent.parent / "src"


def _run_cli(args, workspace: Path, stdin_text=None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(workspace), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True, input=stdin_text,
        env={"PYTHONPATH": str(SRC_DIR)}, timeout=30,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_init_fresh_umask_022_gives_700_600(tmp_path: Path):
    """M1: fresh `acb init` under umask 022 -> dir 700, files 600."""
    ws = tmp_path / "fresh"
    ws.mkdir()
    old = os.umask(0o022)
    try:
        res = _run_cli(["init"], ws)
    finally:
        os.umask(old)
    assert res.returncode == 0, res.stderr
    bridge = ws / ".agent_bridge"
    assert _mode(bridge) == 0o700, oct(_mode(bridge))
    assert _mode(bridge / "records.jsonl") == 0o600
    assert _mode(bridge / "SHARED_CONTEXT.md") == 0o600


def test_initialize_repairs_preexisting_perms(tmp_path: Path):
    """M1: initialize() repairs a pre-existing 755/644 store to 700/600."""
    store = MemoryStore(tmp_path)
    store.initialize()
    os.chmod(store.bridge_dir, 0o755)
    os.chmod(store.records_file, 0o644)
    os.chmod(store.summary_md, 0o644)
    store.initialize()
    assert _mode(store.bridge_dir) == 0o700
    assert _mode(store.records_file) == 0o600
    assert _mode(store.summary_md) == 0o600


def test_add_record_keeps_600_under_umask_022(tmp_path: Path):
    """M1: appended records stay 600 even under a permissive umask."""
    store = MemoryStore(tmp_path)
    store.initialize()
    old = os.umask(0o022)
    try:
        store.add_record(ContextRecord(agent="dev", topic="T", summary="S."))
    finally:
        os.umask(old)
    assert _mode(store.records_file) == 0o600
    assert _mode(store.summary_md) == 0o600


def test_record_warns_on_possible_secret_without_values(tmp_path: Path):
    """H2: `record` warns on stderr (types only) when content looks secret."""
    assert _run_cli(["init"], tmp_path).returncode == 0
    res = _run_cli([
        "record", "--agent", "dev", "--topic", "Keys",
        "--summary", "Rotated integration keys.",
        "--details", "contact dev-fake@example.com for rotation",
    ], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "warning" in res.stderr.lower()
    assert "secret" in res.stderr.lower() or "pii" in res.stderr.lower()
    assert "dev-fake@example.com" not in res.stderr
    assert "dev-fake@example.com" not in res.stdout


def test_record_clean_content_no_warning(tmp_path: Path):
    """H2: a clean record produces no secret warning."""
    assert _run_cli(["init"], tmp_path).returncode == 0
    res = _run_cli([
        "record", "--agent", "dev", "--topic", "Architecture",
        "--summary", "Adopted SQLite WAL mode.",
    ], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "secret" not in res.stderr.lower() and "pii" not in res.stderr.lower()
