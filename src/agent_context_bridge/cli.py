"""Command-line interface for agent-context-bridge."""

import argparse
import json
import sys
from pathlib import Path

from agent_context_bridge.core import MemoryStore, ContextRecord
from agent_context_bridge.adapters import (
    HermesAdapter,
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    CodexAdapter,
)


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--dir", default=".", help="Workspace root directory")

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
        p = store.initialize()
        print(f"✓ Initialized Agent Context Bridge at: {p}")
        print(f"✓ Context document created: {store.summary_md}")

    elif args.command == "record":
        record = ContextRecord(
            agent=args.agent,
            topic=args.topic,
            summary=args.summary,
            details=args.details,
            tags=args.tag,
        )
        store.add_record(record)
        print(f"✓ Recorded [{record.agent}] {record.topic} ({record.estimated_tokens} tokens)")

    elif args.command == "list":
        records = store.list_records(limit=args.limit)
        if not records:
            print("No shared context records found. Run `agent-bridge record` first.")
            return
        print(f"\n--- Shared Context ({len(records)} recent records) ---")
        for r in records:
            print(f"[{r.timestamp[:19]}] [{r.agent}] {r.topic}: {r.summary}")
        print(f"\nFull log: {store.summary_md}")

    elif args.command == "inject":
        adapters = {
            "hermes": HermesAdapter(),
            "claude": ClaudeCodeAdapter(),
            "opencode": OpenCodeAdapter(),
            "codex": CodexAdapter(),
        }
        adapter = adapters[args.target]
        print(adapter.format_prompt_injection(store, max_entries=args.limit))

    elif args.command == "export":
        snap = store.snapshot()
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
