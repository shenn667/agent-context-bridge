"""Hardening tests (step 3 QA): validation limits, corrupted store, adapters caps, --dir placement."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_context_bridge.core import (
    ContextRecord,
    MemoryStore,
    MAX_LIST_LIMIT,
    MAX_AGENT_LEN,
    MAX_TOPIC_LEN,
    MAX_SUMMARY_LEN,
    MAX_DETAILS_LEN,
    MAX_TAGS,
    MAX_TAG_LEN,
)
from agent_context_bridge.adapters import (
    HermesAdapter,
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    CodexAdapter,
    MAX_ADAPTER_ENTRIES,
)


def _cli_base(tmp_path: Path):
    return [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(tmp_path)]


def _env():
    return {"PYTHONPATH": str(Path(__file__).parent.parent / "src")}


def _seed(store_dir: Path, n: int = 2):
    store = MemoryStore(store_dir)
    for i in range(n):
        store.add_record(ContextRecord(agent="dev", topic=f"T{i}", summary=f"Summary {i}."))
    return store


# --- limit validation: list/inject reject 0 and negative with exit 2 ---

def test_list_limit_zero_rejected(tmp_path: Path):
    base = _cli_base(tmp_path)
    res = subprocess.run([*base, "list", "-n", "0"], capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "--limit/-n must be a positive integer" in res.stderr


def test_inject_negative_limit_rejected(tmp_path: Path):
    base = _cli_base(tmp_path)
    res = subprocess.run([*base, "inject", "--limit", "-5"], capture_output=True, text=True, env=_env())
    assert res.returncode == 2
    assert "--limit/-n must be a positive integer" in res.stderr


def test_list_excessive_limit_capped(tmp_path: Path):
    _seed(tmp_path, 3)
    base = _cli_base(tmp_path)
    res = subprocess.run([*base, "list", "--limit", "999999"], capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert "Summary 0." in res.stdout
    # core-level cap check
    store = MemoryStore(tmp_path)
    assert len(store.list_records(limit=999999)) == 3
    assert MAX_LIST_LIMIT == 1000


# --- record validation: empty / too long / tags excessive ---

def test_record_empty_fields_rejected():
    with pytest.raises(ValueError):
        ContextRecord(agent="  ", topic="T", summary="S.")
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="", summary="S.")
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="T", summary="   ")


def test_record_oversize_fields_rejected():
    with pytest.raises(ValueError):
        ContextRecord(agent="x" * (MAX_AGENT_LEN + 1), topic="T", summary="S.")
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="x" * (MAX_TOPIC_LEN + 1), summary="S.")
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="T", summary="x" * (MAX_SUMMARY_LEN + 1))
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="T", summary="S.", details="x" * (MAX_DETAILS_LEN + 1))


def test_record_tags_limits_rejected():
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="T", summary="S.", tags=[f"t{i}" for i in range(MAX_TAGS + 1)])
    with pytest.raises(ValueError):
        ContextRecord(agent="dev", topic="T", summary="S.", tags=["x" * (MAX_TAG_LEN + 1)])


# --- corrupted JSONL line ignored ---

def test_corrupted_jsonl_line_ignored(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    store.add_record(ContextRecord(agent="dev", topic="Good", summary="Valid record."))
    with open(store.records_file, "a", encoding="utf-8") as f:
        f.write("{this is not json\n")
        f.write('{"agent": "dev", "topic": "Broken", "summary": ""}\n')  # fails validation -> skipped
    records = store.list_records()
    assert len(records) == 1
    assert records[0].topic == "Good"


# --- store non-initialized: friendly empty result ---

def test_store_not_initialized_friendly(tmp_path: Path):
    fresh = tmp_path / "nowhere"
    store = MemoryStore(fresh)
    assert store.list_records() == []
    base = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(fresh)]
    res = subprocess.run([*base, "list"], capture_output=True, text=True, env=_env())
    assert res.returncode == 0
    assert "No shared context records found" in res.stdout


# --- adapters max_entries limits ---

def test_adapters_max_entries_limits(tmp_path: Path):
    _seed(tmp_path, 2)
    store = MemoryStore(tmp_path)
    for adapter in [HermesAdapter(), ClaudeCodeAdapter(), OpenCodeAdapter(), CodexAdapter()]:
        assert adapter.format_prompt_injection(store, max_entries=0) == ""
        assert adapter.format_prompt_injection(store, max_entries=-3) == ""
        out = adapter.format_prompt_injection(store, max_entries=10 ** 9)
        assert "Summary" in out  # capped, not crashed
    assert MAX_ADAPTER_ENTRIES == MAX_LIST_LIMIT


# --- --dir accepted before and after subcommand ---

def test_dir_flag_before_and_after_subcommand(tmp_path: Path):
    env = _env()
    src = str(Path(__file__).parent.parent / "src")
    _ = src
    # init with --dir BEFORE subcommand
    res = subprocess.run(
        [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(tmp_path), "init"],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0
    assert "Initialized Agent Context Bridge" in res.stdout
    # record with --dir AFTER subcommand
    res = subprocess.run(
        [sys.executable, "-m", "agent_context_bridge.cli", "record",
         "--dir", str(tmp_path), "--agent", "qa", "--topic", "DirFlag", "--summary", "Dir placement works."],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0
    assert "Recorded [qa] DirFlag" in res.stdout
    # list with --dir AFTER subcommand reads it back
    res = subprocess.run(
        [sys.executable, "-m", "agent_context_bridge.cli", "list", "--dir", str(tmp_path)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0
    assert "Dir placement works." in res.stdout
