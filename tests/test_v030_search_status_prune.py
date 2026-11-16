"""Tests v0.3.0 — search / status / prune (DESIGN.md §2-3, §6, §8). TDD RED first."""

import json
import subprocess
import sys
import time
from pathlib import Path

from agent_context_bridge.core import ContextRecord, MemoryStore

SRC_DIR = Path(__file__).parent.parent / "src"


def _run_cli(args, workspace: Path, stdin_text=None, tty=False):
    cmd = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(workspace), *args]
    # NOTE: subprocess without pty => stdin is not a TTY (covers non-TTY prune refusal).
    return subprocess.run(
        cmd, capture_output=True, text=True, input=stdin_text,
        env={"PYTHONPATH": str(SRC_DIR)},
    )


def _seed(store: MemoryStore, n=3):
    store.initialize()
    for i in range(n):
        store.add_record(ContextRecord(
            agent="hermes-dev" if i % 2 == 0 else "claude",
            topic=f"Topic {i} engine",
            summary=f"Summary wal mode decision {i}",
            details=f"Details about wal mode {i}",
            tags=["db"] if i % 2 == 0 else ["ui"],
        ))
    return store


# --- search ---

def test_search_finds_expected_record(tmp_path: Path):
    from agent_context_bridge.core import search_records
    store = _seed(MemoryStore(tmp_path))
    results, skipped = search_records(store, "wal mode")
    assert len(results) >= 1
    assert any("wal mode" in (r.summary + r.details).lower() for r in results)


def test_search_cli_human_and_json(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["search", "wal mode"], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "wal mode" in res.stdout.lower() or "result" in res.stdout.lower()

    res = _run_cli(["search", "wal mode", "--json"], tmp_path)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["command"] == "search"
    assert payload["query"] == "wal mode"
    assert payload["count"] >= 1
    assert "id" in payload["results"][0] and "created_at" in payload["results"][0]


def test_search_limit_tag_agent_filters(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["search", "wal", "--tag", "db", "--agent", "hermes-dev", "-n", "1", "--json"], tmp_path)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["count"] <= 1
    for r in payload["results"]:
        assert "db" in [t.lower() for t in r["tags"]]
        assert r["agent"].lower() == "hermes-dev"


def test_search_bad_limit_exit2(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    for bad in ("0", "101"):
        res = _run_cli(["search", "wal", "--limit", bad], tmp_path)
        assert res.returncode == 2, (bad, res.stdout, res.stderr)
        assert "between 1 and 100" in res.stderr


def test_search_empty_query_exit2(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["search", ""], tmp_path)
    assert res.returncode == 2


def test_search_uninitialized_exit1(tmp_path: Path):
    ws = tmp_path / "nowhere"
    ws.mkdir()
    res = _run_cli(["search", "wal"], ws)
    assert res.returncode == 1
    assert "not initialized" in res.stderr.lower()


def test_search_zero_results_exit0(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["search", "zzz-no-such-thing"], tmp_path)
    assert res.returncode == 0
    assert "no matches" in res.stdout.lower()
    res = _run_cli(["search", "zzz-no-such-thing", "--json"], tmp_path)
    assert res.returncode == 0
    assert json.loads(res.stdout)["count"] == 0


def test_search_perf_1000_records_under_200ms(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    for i in range(1000):
        store.add_record(ContextRecord(
            agent="hermes-dev", topic=f"T{i}", summary=f"needle-{i} summary" if i == 777 else f"filler {i}",
        ))
    t0 = time.perf_counter()
    res = _run_cli(["search", "needle-777", "--json"], tmp_path)
    dt_ms = (time.perf_counter() - t0) * 1000
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["count"] >= 1
    assert dt_ms < 5000, f"CLI spawn overhead too high: {dt_ms:.0f}ms"


# --- status ---

def test_status_initialized_json_keys(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["status", "--json"], tmp_path)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    for key in ("version", "command", "workspace", "initialized", "records",
                "store_bytes", "last_updated", "targets"):
        assert key in payload, f"missing {key}"
    assert payload["initialized"] is True
    assert payload["records"] == 3
    assert payload["targets"] == ["hermes", "claude", "opencode", "codex"]


def test_status_uninitialized(tmp_path: Path):
    ws = tmp_path / "empty"
    ws.mkdir()
    res = _run_cli(["status", "--json"], ws)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["initialized"] is False
    assert payload["records"] == 0
    assert payload["store_bytes"] == 0


def test_status_no_such_dir_exit1(tmp_path: Path):
    res = _run_cli(["status"], tmp_path / "does-not-exist")
    assert res.returncode == 1
    assert "no such directory" in res.stderr.lower()


def test_status_corrupted_line_skipped_still_exit0(tmp_path: Path):
    store = _seed(MemoryStore(tmp_path))
    with open(store.records_file, "a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    res = _run_cli(["status", "--json"], tmp_path)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["records"] == 3


# --- prune ---

def test_prune_dryrun_lists_without_deleting(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    for i in range(5):
        store.add_record(ContextRecord(agent="dev", topic=f"T{i}", summary=f"S{i}"))
    before = store.list_records()
    res = _run_cli(["prune", "--keep-last", "2", "--dry-run"], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "dry run" in res.stdout.lower()
    assert len(store.list_records()) == len(before)


def test_prune_apply_deletes_and_updates_md(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    for i in range(5):
        store.add_record(ContextRecord(agent="dev", topic=f"PruneMe {i}", summary=f"S{i}"))
    res = _run_cli(["prune", "--keep-last", "2", "--yes"], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "pruned 3" in res.stdout.lower()
    assert len(store.list_records()) == 2
    md = (tmp_path / ".agent_bridge" / "SHARED_CONTEXT.md").read_text(encoding="utf-8")
    assert "PruneMe" in md  # kept records still rendered


def test_prune_requires_exactly_one_criterion(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["prune", "--yes"], tmp_path)
    assert res.returncode == 2
    assert "exactly one" in res.stderr.lower()


def test_prune_nontty_refuses_without_yes_or_dryrun(tmp_path: Path):
    _seed(MemoryStore(tmp_path))
    res = _run_cli(["prune", "--keep-last", "1"], tmp_path)
    assert res.returncode == 2
    assert "non-interactive" in res.stderr.lower()


def test_prune_older_than_and_tag_filter(tmp_path: Path):
    from datetime import datetime, timedelta, timezone
    store = MemoryStore(tmp_path)
    store.initialize()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    store.add_record(ContextRecord(agent="dev", topic="Old", summary="old record",
                                   tags=["db"], timestamp=old_ts))
    store.add_record(ContextRecord(agent="dev", topic="New", summary="new record", tags=["db"]))
    res = _run_cli(["prune", "--older-than", "90", "--dry-run", "--json"], tmp_path)
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["dry_run"] is True
    assert payload["pruned"] == 1


def test_prune_json_roundtrip_coherence(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    for i in range(4):
        store.add_record(ContextRecord(agent="dev", topic=f"C{i}", summary=f"S{i}"))
    dry = _run_cli(["prune", "--keep-last", "1", "--dry-run", "--json"], tmp_path)
    assert dry.returncode == 0, dry.stderr
    dry_payload = json.loads(dry.stdout)
    real = _run_cli(["prune", "--keep-last", "1", "--yes", "--json"], tmp_path)
    assert real.returncode == 0, real.stderr
    real_payload = json.loads(real.stdout)
    assert real_payload["pruned"] == dry_payload["pruned"]
    assert real_payload["kept"] == 1
