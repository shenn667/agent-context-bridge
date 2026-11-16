"""Tests for v0.3.0 commands: search / status / prune (§6 + §8)."""

import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_context_bridge import get_version
from agent_context_bridge.core import ContextRecord, MemoryStore, search_records


def _env():
    return {"PYTHONPATH": str(Path(__file__).parent.parent / "src")}


def _base(tmp_path: Path):
    return [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(tmp_path)]


def _seed(store_dir: Path, specs):
    """specs: list of dicts(agent, topic, summary, details?, tags?, timestamp?)."""
    store = MemoryStore(store_dir)
    for s in specs:
        store.add_record(ContextRecord(
            agent=s.get("agent", "dev"),
            topic=s.get("topic", "T"),
            summary=s.get("summary", "S."),
            details=s.get("details"),
            tags=s.get("tags", []),
            timestamp=s.get("timestamp", datetime.now(timezone.utc).isoformat()),
        ))
    return store


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- search ----------

def test_search_basic_human_newest_first(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": "Old Topic", "summary": "wal mode adopted."},
        {"agent": "hermes-dev", "topic": "Database Engine", "summary": "Adopted SQLite WAL mode."},
    ])
    res = subprocess.run([*_base(tmp_path), "search", "wal", "mode"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert "Database Engine" in res.stdout
    # newest first: Database Engine (seeded last) before Old Topic
    assert res.stdout.index("Database Engine") < res.stdout.index("Old Topic")
    assert "(wal mode)" not in res.stdout  # sanity: no accidental echo
    assert "2 results." in res.stdout
    # short id present in parens
    assert "(" in res.stdout and ")" in res.stdout


def test_search_case_insensitive_or(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "a", "topic": "T1", "summary": "PostgreSQL tuning notes."},
        {"agent": "b", "topic": "T2", "summary": "SQLite WAL mode adopted."},
        {"agent": "c", "topic": "T3", "summary": "Unrelated Redis cache."},
    ])
    res = subprocess.run([*_base(tmp_path), "search", "WAL postgres"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert "T1" in res.stdout and "T2" in res.stdout
    assert "T3" not in res.stdout


def test_search_tag_and_agent_filters(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": "A", "summary": "wal mode here.", "tags": ["db", "perf"]},
        {"agent": "dev", "topic": "B", "summary": "wal mode here.", "tags": ["db"]},
        {"agent": "qa", "topic": "C", "summary": "wal mode here.", "tags": ["db", "perf"]},
    ])
    res = subprocess.run([*_base(tmp_path), "search", "wal", "--tag", "db", "--tag", "perf"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert "Topic" not in res.stdout  # topics are A/B/C
    assert "* [dev] A" in res.stdout and "* [qa] C" in res.stdout
    assert "* [dev] B" not in res.stdout
    # agent filter (case-insensitive exact)
    res2 = subprocess.run([*_base(tmp_path), "search", "wal", "--agent", "QA"],
                          capture_output=True, text=True, env=_env())
    assert res2.returncode == 0, res2.stderr
    assert "* [qa] C" in res2.stdout
    assert "* [dev] A" not in res2.stdout


def test_search_limit_validation(tmp_path: Path):
    _seed(tmp_path, [{"agent": "d", "topic": "T", "summary": "wal here."}])
    for bad in ("0", "-3", "101"):
        res = subprocess.run([*_base(tmp_path), "search", "wal", "-n", bad],
                             capture_output=True, text=True, env=_env())
        assert res.returncode == 2, bad
        assert "must be between 1 and 100" in res.stderr
    # --json error: stdout must stay empty (§6)
    res = subprocess.run([*_base(tmp_path), "search", "wal", "-n", "0", "--json"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert res.stdout == ""
    assert "must be between 1 and 100" in res.stderr


def test_search_empty_query_rejected(tmp_path: Path):
    _seed(tmp_path, [{"agent": "d", "topic": "T", "summary": "S."}])
    res = subprocess.run([*_base(tmp_path), "search"], capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "non-empty" in res.stderr
    res = subprocess.run([*_base(tmp_path), "search", "   "], capture_output=True, text=True, env=_env())
    assert res.returncode == 2


def test_search_zero_results(tmp_path: Path):
    _seed(tmp_path, [{"agent": "d", "topic": "T", "summary": "Something else."}])
    res = subprocess.run([*_base(tmp_path), "search", "wal"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert res.stdout.strip() == 'No matches for "wal".'
    resj = subprocess.run([*_base(tmp_path), "search", "wal", "--json"],
                          capture_output=True, text=True, env=_env())
    assert resj.returncode == 0
    payload = json.loads(resj.stdout)
    assert payload["count"] == 0 and payload["results"] == []


def test_search_json_structure(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "Dev", "topic": "Database Engine", "summary": "Adopted SQLite WAL mode.",
         "details": "Some details.", "tags": ["db"]},
    ])
    res = subprocess.run([*_base(tmp_path), "search", "wal", "--json"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert res.stdout.endswith("\n") and res.stdout.count("\n") == 1
    payload = json.loads(res.stdout)
    assert payload["version"] == get_version() == "0.3.0"
    assert payload["command"] == "search"
    assert payload["query"] == "wal"
    assert payload["count"] == 1
    hit = payload["results"][0]
    assert set(hit) == {"id", "agent", "topic", "summary", "details", "tags", "created_at"}
    assert hit["agent"] == "dev"  # sanitized
    assert hit["tags"] == ["db"]


def test_search_store_not_initialized_and_dir_missing(tmp_path: Path):
    fresh = tmp_path / "nowhere"
    fresh.mkdir()
    res = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                          "--dir", str(fresh), "search", "wal"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 1
    assert "ACB not initialized" in res.stderr
    resj = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                           "--dir", str(fresh), "search", "wal", "--json"],
                          capture_output=True, text=True, env=_env())
    assert resj.returncode == 1
    assert resj.stdout == ""
    missing = tmp_path / "does-not-exist"
    res2 = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                           "--dir", str(missing), "search", "wal"],
                          capture_output=True, text=True, env=_env())
    assert res2.returncode == 1
    assert "no such directory" in res2.stderr


def test_search_corrupted_line_skipped(tmp_path: Path):
    _seed(tmp_path, [{"agent": "d", "topic": "Good", "summary": "wal mode fine."}])
    store = MemoryStore(tmp_path)
    with open(store.records_file, "a", encoding="utf-8") as f:
        f.write("{broken json\n")
    res = subprocess.run([*_base(tmp_path), "search", "wal"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert "Good" in res.stdout
    assert "skipped 1 invalid" in res.stderr
    resj = subprocess.run([*_base(tmp_path), "search", "wal", "--json"],
                          capture_output=True, text=True, env=_env())
    assert resj.returncode == 0
    payload = json.loads(resj.stdout)
    assert payload["skipped"] == 1 and payload["count"] == 1


def test_search_perf_1000_records(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    lines = []
    for i in range(1000):
        summary = f"Routine note number {i}."
        if i == 777:
            summary = "Adopted SQLite WAL mode for local queries."
        rec = ContextRecord(agent="dev", topic=f"Topic {i}", summary=summary,
                            timestamp=_now_iso())
        lines.append(json.dumps(asdict(rec), ensure_ascii=False))
    store.records_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t0 = time.perf_counter()
    results, skipped = search_records(store, "wal mode", limit=10)
    elapsed = time.perf_counter() - t0
    assert skipped == 0
    assert any(r.topic == "Topic 777" for r in results)
    assert elapsed < 0.2, f"search took {elapsed:.3f}s (>200ms)"
    # CLI still returns the record
    res = subprocess.run([*_base(tmp_path), "search", "wal", "mode"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert "Topic 777" in res.stdout


# ---------- status ----------

def test_status_healthy(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": "T1", "summary": "First."},
        {"agent": "qa", "topic": "T2", "summary": "Second."},
    ])
    res = subprocess.run([*_base(tmp_path), "status"], capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert f"ACB {get_version()}" in res.stdout
    assert str(tmp_path) in res.stdout
    assert "Initialized:  yes" in res.stdout
    assert "Records:      2" in res.stdout
    assert "Store size:" in res.stdout and "bytes" in res.stdout
    assert "Last updated:" in res.stdout
    assert "hermes" in res.stdout and "claude" in res.stdout


def test_status_json_exact_keys(tmp_path: Path):
    _seed(tmp_path, [{"agent": "dev", "topic": "T", "summary": "S."}])
    res = subprocess.run([*_base(tmp_path), "status", "--json"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert set(payload) == {"version", "command", "workspace", "initialized",
                            "records", "store_bytes", "last_updated", "targets"}
    assert payload["command"] == "status"
    assert payload["initialized"] is True
    assert payload["records"] == 1
    assert payload["store_bytes"] > 0
    assert payload["last_updated"] is not None
    assert payload["targets"] == ["hermes", "claude", "opencode", "codex"]
    assert payload["workspace"] == str(tmp_path.resolve())


def test_status_not_initialized_never_creates_store(tmp_path: Path):
    fresh = tmp_path / "empty"
    fresh.mkdir()
    res = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                          "--dir", str(fresh), "status"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert "Initialized:  no" in res.stdout
    assert "Records:      0" in res.stdout
    assert not (fresh / ".agent_bridge").exists(), "status must never create the store"
    resj = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                           "--dir", str(fresh), "status", "--json"],
                          capture_output=True, text=True, env=_env())
    payload = json.loads(resj.stdout)
    assert payload == {"version": get_version(), "command": "status",
                       "workspace": str(fresh.resolve()), "initialized": False,
                       "records": 0, "store_bytes": 0, "last_updated": None,
                       "targets": ["hermes", "claude", "opencode", "codex"]}


def test_status_dir_missing_and_corrupted(tmp_path: Path):
    missing = tmp_path / "nope"
    res = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                          "--dir", str(missing), "status"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 1
    assert "no such directory" in res.stderr
    _seed(tmp_path, [{"agent": "d", "topic": "Good", "summary": "S."}])
    store = MemoryStore(tmp_path)
    with open(store.records_file, "a", encoding="utf-8") as f:
        f.write("not json\n")
    res2 = subprocess.run([*_base(tmp_path), "status"], capture_output=True, text=True, env=_env())
    assert res2.returncode == 0  # corrupted line ignored, status stays 0
    assert "skipped 1 invalid" in res2.stderr
    res3 = subprocess.run([*_base(tmp_path), "status", "--json"],
                          capture_output=True, text=True, env=_env())
    assert json.loads(res3.stdout)["skipped"] == 1


# ---------- prune ----------

OLD = "2020-01-01T00:00:00Z"


def test_prune_dry_run_lists_without_deleting(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": "Ancient", "summary": "Old note.", "timestamp": OLD},
        {"agent": "dev", "topic": "Fresh", "summary": "New note.", "timestamp": _now_iso()},
    ])
    store = MemoryStore(tmp_path)
    before = store.records_file.read_text(encoding="utf-8")
    md_before = store.summary_md.read_text(encoding="utf-8")
    res = subprocess.run([*_base(tmp_path), "prune", "--older-than", "90", "--dry-run"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert res.stdout.startswith("Dry run: would prune 1 record(s).")
    assert store.records_file.read_text(encoding="utf-8") == before
    assert store.summary_md.read_text(encoding="utf-8") == md_before
    assert len(store.list_records()) == 2


def test_prune_apply_keep_last_updates_store_and_markdown(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": f"T{i}", "summary": f"Note {i}.",
         "timestamp": f"2024-01-0{i + 1}T00:00:00Z"} for i in range(5)
    ])
    res = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "2", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "Pruned 3 record(s), kept 2."
    store = MemoryStore(tmp_path)
    remaining = store.list_records()
    assert {r.topic for r in remaining} == {"T3", "T4"}
    md = store.summary_md.read_text(encoding="utf-8")
    assert "T3" in md and "T4" in md
    # NOTE: bare "T0" matches timestamps ("T00:00:00Z"); scope to headers.
    for gone in ("T0", "T1", "T2"):
        assert f"] DEV: {gone}" not in md


def test_prune_older_than_apply(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": "Ancient", "summary": "Old.", "timestamp": OLD},
        {"agent": "dev", "topic": "Fresh", "summary": "New.", "timestamp": _now_iso()},
    ])
    res = subprocess.run([*_base(tmp_path), "prune", "--older-than", "90", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "Pruned 1 record(s), kept 1."
    assert [r.topic for r in MemoryStore(tmp_path).list_records()] == ["Fresh"]


def test_prune_exactly_one_and_ranges(tmp_path: Path):
    _seed(tmp_path, [{"agent": "d", "topic": "T", "summary": "S."}])
    res = subprocess.run([*_base(tmp_path), "prune", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "exactly one of --older-than / --keep-last is required." in res.stderr
    res = subprocess.run([*_base(tmp_path), "prune", "--older-than", "10", "--keep-last", "1", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "exactly one of" in res.stderr
    res = subprocess.run([*_base(tmp_path), "prune", "--older-than", "0", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "--older-than must be >= 1" in res.stderr
    res = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "-1", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "--keep-last must be >= 0" in res.stderr
    # keep-last 0 deletes everything
    res = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "0", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert "Pruned 1 record(s), kept 0." in res.stdout


def test_prune_tag_restriction(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": f"T{i}", "summary": f"Note {i}.",
         "tags": ["tmp"] if i % 2 == 0 else ["keep"],
         "timestamp": f"2024-01-0{i + 1}T00:00:00Z"} for i in range(5)
    ])
    # keep-last 1 + tag tmp: newest (T4, tag keep) is kept unconditionally;
    # among the rest only tmp-tagged are pruned (T0, T2); T1/T3 survive.
    res = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "1",
                          "--tag", "tmp", "--yes", "--json"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["pruned"] == 2 and payload["kept"] == 3
    assert payload["dry_run"] is False
    assert {r.topic for r in MemoryStore(tmp_path).list_records()} == {"T1", "T3", "T4"}


def test_prune_non_tty_refusal_and_json_stdout_clean(tmp_path: Path):
    _seed(tmp_path, [{"agent": "d", "topic": "T", "summary": "S.",
                      "timestamp": "2024-01-01T00:00:00Z"}])
    res = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "0"],
                         capture_output=True, text=True, env=_env(),
                         stdin=subprocess.DEVNULL)
    assert res.returncode == 2
    assert "refusing without --yes in non-interactive mode" in res.stderr
    assert len(MemoryStore(tmp_path).list_records()) == 1  # untouched
    resj = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "0", "--json"],
                          capture_output=True, text=True, env=_env(),
                          stdin=subprocess.DEVNULL)
    assert resj.returncode == 2
    assert resj.stdout == ""


def test_prune_json_roundtrip_coherence(tmp_path: Path):
    _seed(tmp_path, [
        {"agent": "dev", "topic": f"T{i}", "summary": f"Note {i}.",
         "timestamp": f"2024-01-0{i + 1}T00:00:00Z"} for i in range(4)
    ])
    dry = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "1", "--yes", "--dry-run", "--json"],
                         capture_output=True, text=True, env=_env())
    assert dry.returncode == 0
    d = json.loads(dry.stdout)
    assert d["dry_run"] is True
    real = subprocess.run([*_base(tmp_path), "prune", "--keep-last", "1", "--yes", "--json"],
                          capture_output=True, text=True, env=_env())
    assert real.returncode == 0
    r = json.loads(real.stdout)
    assert r["dry_run"] is False
    assert (r["pruned"], r["kept"]) == (d["pruned"], d["kept"])
    assert set(r) == {"version", "command", "pruned", "kept", "dry_run", "ids"}
    assert r["command"] == "prune" and r["version"] == "0.3.0"


def test_prune_not_initialized_and_dir_missing(tmp_path: Path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    res = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                          "--dir", str(fresh), "prune", "--keep-last", "1", "--yes"],
                         capture_output=True, text=True, env=_env())
    assert res.returncode == 1
    assert "ACB not initialized" in res.stderr
    missing = tmp_path / "missing"
    res2 = subprocess.run([sys.executable, "-m", "agent_context_bridge.cli",
                           "--dir", str(missing), "prune", "--keep-last", "1", "--yes"],
                          capture_output=True, text=True, env=_env())
    assert res2.returncode == 1
    assert "no such directory" in res2.stderr


def test_help_documents_all_flags(tmp_path: Path):
    for cmd, flags in [
        (["search", "--help"], ["--dir", "--json", "-n", "--limit", "--tag", "--agent"]),
        (["status", "--help"], ["--dir", "--json"]),
        (["prune", "--help"], ["--dir", "--older-than", "--keep-last", "--tag",
                               "--dry-run", "--yes", "--json"]),
    ]:
        res = subprocess.run([*_base(tmp_path), *cmd], capture_output=True, text=True, env=_env())
        assert res.returncode == 0
        for f in flags:
            assert f in res.stdout, (cmd, f)
