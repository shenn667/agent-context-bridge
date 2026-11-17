"""MCP stdio JSON-RPC server for agent-context-bridge (zero-dependency).

Binary ``acb-mcp``. Exposes (strict READONLY):

- ``acb_search``  -> core.search_records (read-only)
- ``acb_status``  -> core.get_status (read-only)

``prune`` stays CLI-only (DESIGN.md §4). Any other tool name
(``tools/call`` with an unknown name, or any unknown method) answers
``Method not found`` and never touches the store.

The client-supplied ``dir`` argument is confined under the server
``--dir`` root: anything outside answers ``-32602`` without probing
the filesystem.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_context_bridge import get_version
from agent_context_bridge.core import (
    MemoryStore,
    get_status,
    record_to_search_dict,
    search_records,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "acb-mcp"

TOOL_NAMES = ("acb_search", "acb_status")

SERVER_INSTRUCTIONS = (
    "Agent Context Bridge: shared offline memory across coding agents "
    "(Hermes, Claude Code, OpenCode, Codex). "
    "2 strictly read-only tools. Call acb_status first to verify the "
    "workspace store is initialized and non-empty; then call acb_search to "
    "recall past decisions, constraints, and task notes before acting. "
    "Recording, pruning, and auditing are CLI-only (acb record/prune/audit) "
    "and intentionally unavailable here, so this server can never modify state."
)

# MCP annotation hints (captured by Glama introspection): both tools are
# side-effect free, non-destructive, idempotent, and offline-only.
_READONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _tool_defs() -> List[Dict[str, Any]]:
    return [
        {
            "name": "acb_search",
            "annotations": dict(_READONLY_ANNOTATIONS),
            "description": (
                "Read-only full-text search over the shared agent context store "
                "(.agent_bridge/records.jsonl). OR-combined case-insensitive match "
                "on topic/summary/details/tags, newest-first. Never writes or prunes; "
                "use to find prior decisions before acting. "
                "Returns {version, command, query, count, results[], skipped}."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "1+ words, OR-combined, case-insensitive; "
                            "e.g. 'auth decision'. Required, non-empty."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 10,
                        "description": "Max hits 1..100, default 10, newest-first.",
                    },
                    "tag": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tag filter list, e.g. ['db']; ANDed with query.",
                    },
                    "agent": {
                        "type": "string",
                        "description": (
                            "Optional agent-name filter, exact case-insensitive match, "
                            "e.g. 'hermes-dev'."
                        ),
                    },
                    "dir": {
                        "type": "string",
                        "description": (
                            "Optional workspace path confined under the server --dir root; "
                            "outside root rejected (-32602). Default: server cwd."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "acb_status",
            "annotations": dict(_READONLY_ANNOTATIONS),
            "description": (
                "Read-only workspace diagnostic for the shared context store. "
                "Returns {initialized, records, store_bytes, last_updated, targets, version}. "
                "Never creates the store; uninitialized workspace returns initialized:false. "
                "Use to verify ACB wiring/health before search/inject."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "dir": {
                        "type": "string",
                        "description": (
                            "Optional workspace path confined under the server --dir root; "
                            "outside root rejected (-32602). Default: server cwd."
                        ),
                    },
                },
            },
        },
    ]


def _resolve_workspace(dir_param: Any, default_dir: Path) -> Path:
    if dir_param is None:
        return default_dir
    if not isinstance(dir_param, str) or not dir_param.strip():
        raise ValueError("dir must be a non-empty string path.")
    return Path(dir_param).expanduser().resolve()


def _is_within(child: Path, parent: Path) -> bool:
    """True when ``child`` == ``parent`` or is nested under it (H1/bis)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _text_result(payload: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
    }
    if is_error:
        out["isError"] = True
    return out


def _call_search(args: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query: string (non-empty) is required.")
    limit = args.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    tags = args.get("tag", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise ValueError("tag must be an array of strings.")
    agent = args.get("agent")
    if agent is not None and not isinstance(agent, str):
        raise ValueError("agent must be a string.")
    if not workspace.exists():
        return _text_result({"error": f"no such directory: {workspace}"}, is_error=True)
    store = MemoryStore(workspace)
    if not store.records_file.exists():
        return _text_result(
            {"error": f"ACB not initialized in {workspace} (run 'acb init')."},
            is_error=True,
        )
    try:
        results, skipped = search_records(store, query, limit=limit, tags=tags, agent=agent)
    except ValueError as exc:
        raise ValueError(str(exc))
    payload: Dict[str, Any] = {
        "version": get_version(),
        "command": "search",
        "query": query.strip(),
        "count": len(results),
        "results": [record_to_search_dict(r) for r in results],
    }
    if skipped:
        payload["skipped"] = skipped
    return _text_result(payload)


def _call_status(args: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
    if not workspace.exists():
        return _text_result({"error": f"no such directory: {workspace}"}, is_error=True)
    store = MemoryStore(workspace)
    try:
        info = get_status(store)
    except OSError as exc:
        return _text_result({"error": f"failed to read status: {exc}"}, is_error=True)
    payload = {"command": "status", **info}
    return _text_result(payload)


def handle_message(msg: Any, default_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC message; return the response dict or None (notification)."""
    base_dir = Path(default_dir).resolve() if default_dir else Path.cwd().resolve()

    def _err(req_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    if not isinstance(msg, dict):
        return _err(None, -32600, "Invalid Request: expected an object.")
    if msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _err(msg.get("id"), -32600, "Invalid Request: missing jsonrpc/method.")
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        # tools/call expects object params; tools/list tolerates anything.
        if method == "tools/call":
            if req_id is None:
                return None
            return _err(req_id, -32602, "Invalid params: params must be an object.")

    # Notifications (no id): no response.
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": get_version()},
                "instructions": SERVER_INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_defs()}}
    if method in ("resources/list", "prompts/list"):
        # This server exposes no resources or prompts; answer with an empty
        # list (instead of -32601) so naive introspectors succeed.
        key = "resources" if method == "resources/list" else "prompts"
        return {"jsonrpc": "2.0", "id": req_id, "result": {key: []}}
    if method == "tools/call":
        if not isinstance(params, dict):
            return _err(req_id, -32602, "Invalid params: params must be an object.")
        name = params.get("name")
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _err(req_id, -32602, "Invalid params: arguments must be an object.")
        try:
            workspace = _resolve_workspace(args.get("dir"), base_dir)
        except ValueError as exc:
            return _err(req_id, -32602, f"Invalid params: {exc}")
        # H1/bis: confine the client-supplied `dir` under the server --dir.
        # Anything outside the server root is rejected (-32602), never probed.
        if not _is_within(workspace, base_dir):
            return _err(
                req_id, -32602,
                "Invalid params: dir must be within the server workspace "
                f"({base_dir}).",
            )
        try:
            if name == "acb_search":
                result = _call_search(args, workspace)
            elif name == "acb_status":
                result = _call_status(args, workspace)
            else:
                return _err(req_id, -32601, f"Method not found: {name!r}.")
        except ValueError as exc:
            return _err(req_id, -32602, f"Invalid params: {exc}")
        except Exception as exc:  # never leak a traceback over the wire
            return _err(req_id, -32603, f"Internal error: {exc}")
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    return _err(req_id, -32601, f"Method not found: {method!r}.")


def main(argv: Optional[List[str]] = None) -> None:
    """Serve JSON-RPC over stdio (one JSON object per line)."""
    parser = argparse.ArgumentParser(
        prog="acb-mcp",
        description="ACB MCP server (stdio JSON-RPC, readonly tools).",
    )
    parser.add_argument("--dir", default=".", help="Default workspace root")
    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")
    args = parser.parse_args(argv)
    default_dir = Path(args.dir).resolve()
    data = sys.stdin
    out = sys.stdout
    for raw in data:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            out.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }) + "\n")
            out.flush()
            continue
        try:
            resp = handle_message(msg, default_dir=default_dir)
        except Exception as exc:
            resp = {
                "jsonrpc": "2.0",
                "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
        if resp is None:
            continue
        out.write(json.dumps(resp, ensure_ascii=False) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
