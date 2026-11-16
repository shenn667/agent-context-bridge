"""Tests v0.3.0 — acb-mcp stdio JSON-RPC (DESIGN.md §4). TDD RED first."""

import json
import subprocess
import sys
from pathlib import Path

from agent_context_bridge.core import ContextRecord, MemoryStore

SRC_DIR = Path(__file__).parent.parent / "src"


def _mcp_call(messages, workspace: Path):
    """Send newline-delimited JSON-RPC messages to acb-mcp, return response lines."""
    proc = subprocess.run(
        [sys.executable, "-m", "agent_context_bridge.mcp", "--dir", str(workspace)],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True, text=True,
        env={"PYTHONPATH": str(SRC_DIR)},
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
    return out


def _seed(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()
    store.add_record(ContextRecord(agent="hermes-dev", topic="Database Engine",
                                   summary="Adopted SQLite WAL mode", tags=["db"]))
    return store


def test_mcp_tools_list_exposes_only_search_status_readonly(tmp_path: Path):
    _seed(tmp_path)
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ], tmp_path)
    by_id = {m["id"]: m for m in out if "id" in m}
    names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert names == {"acb_search", "acb_status"}


def test_mcp_search_returns_record(tmp_path: Path):
    _seed(tmp_path)
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_search", "arguments": {"query": "wal mode"}}},
    ], tmp_path)
    assert "result" in out[0]
    text = out[0]["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert payload["count"] >= 1


def test_mcp_status_ok(tmp_path: Path):
    _seed(tmp_path)
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_status", "arguments": {}}},
    ], tmp_path)
    payload = json.loads(out[0]["result"]["content"][0]["text"])
    assert payload["initialized"] is True
    assert payload["records"] == 1


def test_mcp_prune_is_method_not_found_store_unchanged(tmp_path: Path):
    store = _seed(tmp_path)
    for i in range(3):
        store.add_record(ContextRecord(agent="dev", topic=f"T{i}", summary=f"S{i}"))
    before = len(store.list_records())
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_prune", "arguments": {"keep_last": 1}}},
    ], tmp_path)
    assert "error" in out[0]
    assert out[0]["error"]["code"] == -32601
    assert len(store.list_records()) == before, "MCP must never mutate the store"


def test_mcp_prune_dryrun_false_explicit_store_unchanged(tmp_path: Path):
    """H1 re-test: explicit dry_run:false must also be refused (no mutation)."""
    store = _seed(tmp_path)
    for i in range(3):
        store.add_record(ContextRecord(agent="dev", topic=f"T{i}", summary=f"S{i}"))
    before = store.records_file.read_text(encoding="utf-8")
    variants = [
        {"keep_last": 0, "dry_run": False},
        {"keep_last": 1, "dry_run": False},
        {"older_than": 30, "dry_run": False},
        {"dry_run": False},
    ]
    for i, arguments in enumerate(variants):
        out = _mcp_call([
            {"jsonrpc": "2.0", "id": i + 1, "method": "tools/call",
             "params": {"name": "acb_prune", "arguments": arguments}},
        ], tmp_path)
        assert "error" in out[0], arguments
        assert out[0]["error"]["code"] == -32601, arguments
    assert store.records_file.read_text(encoding="utf-8") == before
    assert len(store.list_records()) == 4


def test_mcp_unknown_tool_method_not_found(tmp_path: Path):
    _seed(tmp_path)
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_write", "arguments": {}}},
    ], tmp_path)
    assert "error" in out[0]
    assert out[0]["error"]["code"] == -32601


def test_mcp_invalid_params_32602(tmp_path: Path):
    _seed(tmp_path)
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_search", "arguments": {"limit": 999}}},
    ], tmp_path)
    assert "error" in out[0]
    assert out[0]["error"]["code"] == -32602


def test_mcp_uninitialized_is_error(tmp_path: Path):
    ws = tmp_path / "empty"
    ws.mkdir()
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_search", "arguments": {"query": "x"}}},
    ], tmp_path / "empty")
    msg = json.dumps(out[0])
    assert "isError" in msg or "error" in msg


def test_mcp_dir_outside_server_root_rejected_32602(tmp_path: Path):
    """H1/bis: a client `dir` outside the server --dir is refused (-32602)."""
    _seed(tmp_path)
    for outsider in ("/etc", "/tmp", str(tmp_path.parent)):
        out = _mcp_call([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "acb_search",
                        "arguments": {"query": "x", "dir": outsider}}},
        ], tmp_path)
        assert "error" in out[0], outsider
        assert out[0]["error"]["code"] == -32602, outsider
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "acb_status",
                    "arguments": {"dir": "/etc/passwd"}}},
    ], tmp_path)
    assert out[0]["error"]["code"] == -32602


def test_mcp_dir_inside_server_root_allowed(tmp_path: Path):
    """A `dir` nested under the server root still works (confinement)."""
    _seed(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    from agent_context_bridge.core import MemoryStore as _MS
    _MS(sub).initialize()
    out = _mcp_call([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "acb_status", "arguments": {"dir": str(sub)}}},
    ], tmp_path)
    assert "result" in out[0]
    payload = json.loads(out[0]["result"]["content"][0]["text"])
    assert payload["initialized"] is True
