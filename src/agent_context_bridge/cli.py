"""Command-line interface for agent-context-bridge."""

import argparse
import json
import sys
from pathlib import Path

from agent_context_bridge.core import MemoryStore, ContextRecord, MAX_LIST_LIMIT
from agent_context_bridge.adapters import (
    HermesAdapter,
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    CodexAdapter,
)


def _require_valid_limit(parser: argparse.ArgumentParser, limit) -> int:
    """Validate --limit/-n: reject <= 0 with exit code 2, cap at MAX_LIST_LIMIT."""
    if limit is None:
        return 10
    if limit <= 0:
        parser.error(f"--limit/-n must be a positive integer (got {limit}).")
    return min(limit, MAX_LIST_LIMIT)


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    # NOTE: default=SUPPRESS so the subparser-level --dir does not shadow a
    # top-level `--dir <path>` with its own default (classic argparse pitfall).
    parent_parser.add_argument("--dir", default=argparse.SUPPRESS, help="Workspace root directory")

    parser = argparse.ArgumentParser(
        prog="agent-bridge",
        description="Agent Context Bridge (ACB) — Universal memory & context handoff for coding agents.",
        parents=[parent_parser],
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize ACB in current workspace", parents=[parent_parser])

    # record
    record_parser = subparsers.add_parser("record", help="Record a new context item", parents=[parent_parser])
    record_parser.add_argument("--agent", required=True, help="Agent name (e.g. hermes, claude, opencode)")
    record_parser.add_argument("--topic", required=True, help="Short topic/scope of the decision")
    record_parser.add_argument("--summary", required=True, help="1-sentence executive summary")
    record_parser.add_argument("--details", help="Optional detailed markdown explanation")
    record_parser.add_argument("--tag", action="append", default=[], help="Categorization tag (repeatable)")

    # list
    list_parser = subparsers.add_parser("list", help="List recent shared context items", parents=[parent_parser])
    list_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum items to show")

    # inject
    inject_parser = subparsers.add_parser("inject", help="Output formatted context for specific agent", parents=[parent_parser])
    inject_parser.add_argument(
        "--target",
        choices=["hermes", "claude", "opencode", "codex"],
        default="hermes",
        help="Target agent prompt format",
    )
    inject_parser.add_argument("-n", "--limit", type=int, default=5, help="Maximum items to inject")

    # export
    export_parser = subparsers.add_parser("export", help="Export full snapshot to JSON", parents=[parent_parser])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    workspace = Path(getattr(args, "dir", ".")).resolve()
    store = MemoryStore(workspace)

    if args.command == "init":
        try:
            p = store.initialize()
        except OSError as exc:
            print(f"error: failed to initialize store at {store.bridge_dir}: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ Initialized Agent Context Bridge at: {p}")
        print(f"✓ Context document created: {store.summary_md}")

    elif args.command == "record":
        try:
            record = ContextRecord(
                agent=args.agent,
                topic=args.topic,
                summary=args.summary,
                details=args.details,
                tags=args.tag,
            )
        except ValueError as exc:
            print(f"error: invalid record: {exc}", file=sys.stderr)
            sys.exit(2)
        try:
            store.add_record(record)
        except (OSError, ValueError) as exc:
            print(f"error: failed to record context: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ Recorded [{record.agent}] {record.topic} ({record.estimated_tokens} tokens)")

    elif args.command == "list":
        limit = _require_valid_limit(parser, args.limit)
        try:
            records = store.list_records(limit=limit)
        except OSError as exc:
            print(f"error: failed to list records: {exc}", file=sys.stderr)
            sys.exit(1)
        if not records:
            print("No shared context records found. Run `agent-bridge record` first.")
            return
        print(f"\n--- Shared Context ({len(records)} recent records) ---")
        for r in records:
            print(f"[{r.timestamp[:19]}] [{r.agent}] {r.topic}: {r.summary}")
        print(f"\nFull log: {store.summary_md}")

    elif args.command == "inject":
        limit = _require_valid_limit(parser, args.limit)
        adapters = {
            "hermes": HermesAdapter(),
            "claude": ClaudeCodeAdapter(),
            "opencode": OpenCodeAdapter(),
            "codex": CodexAdapter(),
        }
        adapter = adapters[args.target]
        try:
            output = adapter.format_prompt_injection(store, max_entries=limit)
        except OSError as exc:
            print(f"error: failed to inject context: {exc}", file=sys.stderr)
            sys.exit(1)
        if not output.strip():
            print("No shared context records found. Run `agent-bridge record` first.")
            return
        print(output)

    elif args.command == "export":
        try:
            snap = store.snapshot()
        except OSError as exc:
            print(f"error: failed to export snapshot: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
