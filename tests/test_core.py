"""Tests for core data models and storage."""

import json
from pathlib import Path
from agent_context_bridge.core import ContextRecord, MemoryStore, BridgeSnapshot


def test_context_record_serialization():
    rec = ContextRecord(
        agent="Dev-Hermes",
        topic="Database Choice",
        summary="Switched to SQLite with WAL mode for local zero-latency queries.",
        details="PostgreSQL was too heavy for local single-node agent deployment.",
        tags=["db", "architecture"],
    )
    assert rec.agent == "dev-hermes"
    assert rec.estimated_tokens > 0
    md = rec.to_markdown()
    assert "DEV-HERMES: Database Choice" in md
    assert "Switched to SQLite with WAL mode" in md
    assert "**Tags:** `db, architecture`" in md


def test_memory_store_roundtrip(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()

    assert (tmp_path / ".agent_bridge" / "records.jsonl").exists()
    assert (tmp_path / ".agent_bridge" / "SHARED_CONTEXT.md").exists()

    rec1 = ContextRecord(agent="cto", topic="Architecture", summary="Split into micro-packages.")
    rec2 = ContextRecord(agent="dev", topic="Implementation", summary="Completed auth module.")

    store.add_record(rec1)
    store.add_record(rec2)

    records = store.list_records()
    assert len(records) == 2
    # newest first
    assert records[0].topic == "Implementation"
    assert records[1].topic == "Architecture"

    # Verify Markdown generated
    md_content = (tmp_path / ".agent_bridge" / "SHARED_CONTEXT.md").read_text(encoding="utf-8")
    assert "Implementation" in md_content
    assert "Architecture" in md_content


def test_snapshot_generation(tmp_path: Path):
    from agent_context_bridge import get_version
    store = MemoryStore(tmp_path)
    store.add_record(ContextRecord(agent="qa", topic="Testing", summary="All tests passed."))
    snap = store.snapshot()

    assert isinstance(snap, BridgeSnapshot)
    assert snap.version == get_version()
    assert len(snap.records) == 1
    assert snap.total_tokens > 0

    d = snap.to_dict()
    assert d["total_tokens"] == snap.total_tokens
    assert len(d["records"]) == 1
