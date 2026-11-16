"""Command-line interface for agent-context-bridge."""

import argparse
import json
import sys
from pathlib import Path

from agent_context_bridge.core import (
    MemoryStore,
    ContextRecord,
    MAX_LIST_LIMIT,
    MAX_SEARCH_LIMIT,
    get_status,
    prune_records,
    record_id,
    record_to_search_dict,
    search_records,
)
from agent_context_bridge import get_version
from agent_context_bridge.audit import MASK as AUDIT_MASK, audit_store, scan_line
from agent_context_bridge.hooks import (
    HOOK_TARGETS,
    DEFAULT_MAX_ENTRIES,
    hook_command,
    render_claude_settings_snippet,
    hermes_wiring_snippet,
    install_claude_hook,
    run_hook_injection,
)
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


def _require_valid_search_limit(parser: argparse.ArgumentParser, limit) -> int:
    """Validate search --limit/-n: must be within 1..MAX_SEARCH_LIMIT (exit 2)."""
    if limit is None:
        return 10
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        parser.error(f"--limit/-n must be between 1 and {MAX_SEARCH_LIMIT} (got {limit}).")
    return limit


def _check_workspace_dir(parser: argparse.ArgumentParser, workspace: Path, as_json: bool = False) -> None:
    """Exit 1 when --dir points at a non-existent path (no implicit creation)."""
    if not workspace.exists():
        print(f"error: no such directory: {workspace}", file=sys.stderr)
        sys.exit(1)


def _not_initialized(workspace: Path) -> None:
    print(f"ACB not initialized in {workspace} (run 'acb init').", file=sys.stderr)
    sys.exit(1)


def _trunc_line(text: str, width: int = 100) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


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
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Show package version (coherent with git tag vX.Y.Z and pyproject).",
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

    # search (§2.1)
    search_parser = subparsers.add_parser(
        "search", help="Full-text search over shared context", parents=[parent_parser]
    )
    search_parser.add_argument("query", nargs="*", help="1+ words, OR-combined (case-insensitive)")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Max results 1..100 (default 10)")
    search_parser.add_argument("--tag", action="append", default=[], help="Filter: record must carry ALL tags (repeatable)")
    search_parser.add_argument("--agent", default=None, help="Filter: exact agent name (case-insensitive)")
    search_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # status (§2.2)
    status_parser = subparsers.add_parser(
        "status", help="Read-only workspace diagnostic", parents=[parent_parser]
    )
    status_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # audit (§C2) — read-only secrets/PII scan, exit 1 if findings.
    audit_parser = subparsers.add_parser(
        "audit", help="Scan records for secrets/PII (exit 1 if found, values masked)",
        parents=[parent_parser],
    )
    audit_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # prune (§2.3) — SEULE commande destructive
    prune_parser = subparsers.add_parser(
        "prune", help="Delete old entries (destructive: confirmation required)", parents=[parent_parser]
    )
    prune_parser.add_argument("--older-than", type=int, default=None, metavar="DAYS",
                              help="Delete records older than DAYS (>= 1)")
    prune_parser.add_argument("--keep-last", type=int, default=None, metavar="N",
                              help="Keep N newest records, delete the rest (>= 0)")
    prune_parser.add_argument("--tag", action="append", default=[],
                              help="Restrict deletion to records carrying ALL tags (repeatable)")
    prune_parser.add_argument("--dry-run", action="store_true",
                              help="List what would be deleted without deleting")
    prune_parser.add_argument("--yes", action="store_true",
                              help="Skip interactive confirmation (required non-TTY)")
    prune_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # hooks
    hooks_parser = subparsers.add_parser(
        "hooks", help="Native agent hooks (Claude SessionStart, Hermes inject)", parents=[parent_parser]
    )
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_action", help="Hook operations")

    hooks_claude = hooks_sub.add_parser("claude", help="Claude Code SessionStart hook", parents=[parent_parser])
    hooks_claude.add_argument("--print", dest="print_snippet", action="store_true",
                              help="Print .claude/settings.json snippet (default)")
    hooks_claude.add_argument("--install", action="store_true",
                              help="Write/merge hook into <workspace>/.claude/settings.json")
    hooks_claude.add_argument("-n", "--max-entries", type=int, default=DEFAULT_MAX_ENTRIES,
                              help="Maximum context entries injected per session")

    hooks_hermes = hooks_sub.add_parser("hermes", help="Hermes Agent inject wiring", parents=[parent_parser])
    hooks_hermes.add_argument("--print", dest="print_snippet", action="store_true", default=True,
                              help="Print one-command Hermes wiring snippet")

    hooks_run = hooks_sub.add_parser("run", help="Execute hook injection (reads hook JSON on stdin, prints context on stdout)",
                                     parents=[parent_parser])
    hooks_run.add_argument("--target", choices=list(HOOK_TARGETS), default="hermes",
                           help="Target agent prompt format")
    hooks_run.add_argument("-n", "--max-entries", type=int, default=DEFAULT_MAX_ENTRIES,
                           help="Maximum entries to inject")

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
        # H2: warn (stderr, non-blocking) when the content looks like a
        # secret/PII — values are stored in clear text. Types only, never
        # the matched values.
        _hits = scan_line(" ".join([
            str(record.topic or ""), str(record.summary or ""),
            str(record.details or ""), " ".join(record.tags or []),
        ]))
        if _hits:
            _types = ", ".join(sorted(_hits))
            print(f"warning: possible secret/PII detected ({_types}). "
                  f"Values are stored in clear text in records.jsonl; "
                  f"run 'acb audit' to review.", file=sys.stderr)
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

    elif args.command == "search":
        query = " ".join(args.query or []).strip()
        if not query:
            parser.error("search requires a non-empty <query>.")
        limit = _require_valid_search_limit(parser, args.limit)
        _check_workspace_dir(parser, workspace, as_json=args.json)
        if not store.records_file.exists():
            _not_initialized(workspace)
        try:
            results, skipped = search_records(
                store, query, limit=limit, tags=args.tag or [], agent=args.agent
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
        if args.json:
            payload = {
                "version": get_version(),
                "command": "search",
                "query": query,
                "count": len(results),
                "results": [record_to_search_dict(r) for r in results],
            }
            if skipped:
                payload["skipped"] = skipped
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            if skipped:
                print(f"warning: skipped {skipped} invalid record(s).", file=sys.stderr)
            return
        if skipped:
            print(f"warning: skipped {skipped} invalid record(s).", file=sys.stderr)
        if not results:
            print(f'No matches for "{query}".')
            return
        for r in results:
            print(_trunc_line(f"* [{r.agent}] {r.topic} \u2014 {r.summary} ({record_id(r)})"))
        print(f"  {len(results)} result." if len(results) == 1 else f"  {len(results)} results.")
        if len(results) == 1:
            only = results[0]
            if only.tags:
                print(_trunc_line(f"  Tags: {', '.join(only.tags)}"))
            print(_trunc_line(f"  Created: {only.timestamp}"))
            if only.details and str(only.details).strip():
                print(_trunc_line(f"  Details: {str(only.details).strip()}".replace("\n", " "), width=500))

    elif args.command == "status":
        _check_workspace_dir(parser, workspace, as_json=args.json)
        try:
            info = get_status(store)
        except OSError as exc:
            print(f"error: failed to read status: {exc}", file=sys.stderr)
            sys.exit(1)
        skipped = int(info.get("skipped", 0) or 0)
        if args.json:
            payload = {"command": "status", **{k: v for k, v in info.items() if k != "skipped"}}
            if skipped:
                payload["skipped"] = skipped
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            if skipped:
                print(f"warning: skipped {skipped} invalid record(s).", file=sys.stderr)
            return
        if skipped:
            print(f"warning: skipped {skipped} invalid record(s).", file=sys.stderr)
        last = info.get("last_updated") or "never"
        print(f"ACB {info.get('version')}")
        print(f"Workspace:    {info.get('workspace')}")
        print(f"Initialized:  {'yes' if info.get('initialized') else 'no'}")
        print(f"Records:      {info.get('records')}")
        print(f"Store size:   {info.get('store_bytes')} bytes")
        print(f"Last updated: {last}")
        print(f"Targets:      {', '.join(info.get('targets', []))}")

    elif args.command == "audit":
        _check_workspace_dir(parser, workspace, as_json=args.json)
        if not store.records_file.exists():
            _not_initialized(workspace)
        try:
            report = audit_store(store)
        except OSError as exc:
            print(f"error: failed to audit store: {exc}", file=sys.stderr)
            sys.exit(1)
        n_records = int(report.get("records", 0))
        counts = dict(report.get("counts", {}))
        findings = list(report.get("findings", []))
        clean = not findings
        if args.json:
            payload = {
                "version": get_version(),
                "command": "audit",
                "records": n_records,
                "clean": clean,
                "total_findings": int(report.get("total_findings", 0)),
                "counts": counts,
                "findings": findings,
            }
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.exit(0 if clean else 1)
        if clean:
            print(f"✓ No secrets/PII detected in {n_records} record(s).")
            return
        # Findings: report type/count/lines only — values never printed (masked).
        print(f"ACB audit: {len(findings)} finding(s) in {n_records} record(s) "
              f"(values masked [{AUDIT_MASK}]).")
        for f in findings:
            print(f"  - {f.get('type')}: {f.get('count')} occurrence(s) "
                  f"on line {f.get('line')} [{AUDIT_MASK}]")
        sys.exit(1)

    elif args.command == "prune":
        _check_workspace_dir(parser, workspace, as_json=args.json)
        if not store.records_file.exists():
            _not_initialized(workspace)
        older_than = args.older_than
        keep_last = args.keep_last
        if (older_than is None) == (keep_last is None):
            parser.error("exactly one of --older-than / --keep-last is required.")
        if older_than is not None and older_than < 1:
            parser.error(f"--older-than must be >= 1 (got {older_than}).")
        if keep_last is not None and keep_last < 0:
            parser.error(f"--keep-last must be >= 0 (got {keep_last}).")
        try:
            preview = prune_records(
                store, older_than=older_than, keep_last=keep_last,
                tags=args.tag or [], dry_run=True,
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            msg = str(exc)
            if isinstance(exc, FileNotFoundError):
                print(msg, file=sys.stderr)
                sys.exit(1)
            if "exactly one of" in msg or "must be >=" in msg:
                parser.error(msg)
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        n_prune = int(preview.get("pruned", 0))
        n_kept = int(preview.get("kept", 0))
        skipped = int(preview.get("skipped", 0) or 0)
        if args.dry_run:
            if args.json:
                payload = {
                    "version": get_version(),
                    "command": "prune",
                    "pruned": n_prune,
                    "kept": n_kept,
                    "dry_run": True,
                    "ids": preview.get("ids", []),
                }
                if skipped:
                    payload["skipped"] = skipped
                sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            else:
                print(f"Dry run: would prune {n_prune} record(s).")
                for pid in preview.get("ids", []):
                    print(f"  - {pid}")
            if skipped:
                print(f"warning: skipped {skipped} invalid record(s).", file=sys.stderr)
            return
        # Real deletion requires confirmation.
        if not args.yes:
            if not sys.stdin.isatty():
                print("error: refusing without --yes in non-interactive mode "
                      "(use --dry-run to preview or --yes to confirm).", file=sys.stderr)
                sys.exit(2)
            print(f"Prune {n_prune} record(s)? [y/N] ", end="", file=sys.stderr)
            try:
                answer = input().strip().lower()
            except (EOFError, OSError):
                answer = ""
            if answer not in ("y", "yes"):
                if args.json:
                    payload = {
                        "version": get_version(),
                        "command": "prune",
                        "pruned": 0,
                        "kept": n_prune + n_kept,
                        "dry_run": True,
                        "ids": [],
                    }
                    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
                else:
                    print("Aborted, 0 pruned.")
                return
        try:
            result = prune_records(
                store, older_than=older_than, keep_last=keep_last,
                tags=args.tag or [], dry_run=False,
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        skipped = int(result.get("skipped", 0) or 0)
        if args.json:
            payload = {
                "version": get_version(),
                "command": "prune",
                "pruned": int(result.get("pruned", 0)),
                "kept": int(result.get("kept", 0)),
                "dry_run": False,
                "ids": result.get("ids", []),
            }
            if skipped:
                payload["skipped"] = skipped
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        else:
            print(f"Pruned {int(result.get('pruned', 0))} record(s), kept {int(result.get('kept', 0))}.")
        if skipped:
            print(f"warning: skipped {skipped} invalid record(s).", file=sys.stderr)

    elif args.command == "hooks":
        action = args.hooks_action
        if action == "claude":
            max_entries = args.max_entries if args.max_entries and args.max_entries > 0 else DEFAULT_MAX_ENTRIES
            if args.install:
                try:
                    settings_path = install_claude_hook(workspace, max_entries=max_entries)
                except OSError as exc:
                    print(f"error: failed to install Claude hook: {exc}", file=sys.stderr)
                    sys.exit(1)
                print(f"✓ Claude SessionStart hook installed: {settings_path}")
                print(f"  command: {hook_command('claude', max_entries)}")
            else:
                print(render_claude_settings_snippet(max_entries=max_entries))
        elif action == "hermes":
            print(hermes_wiring_snippet())
        elif action == "run":
            # Drain hook payload on stdin (Claude SessionStart JSON); content is
            # intentionally ignored (never interpolated). Bounded read (M2: 1 Mo
            # max) to avoid a memory spike on an abnormally large payload.
            try:
                if not sys.stdin.isatty():
                    sys.stdin.read(1_000_000)
            except (OSError, ValueError):
                pass
            limit = args.max_entries
            if limit is not None and limit <= 0:
                parser.error("--max-entries must be a positive integer.")
            try:
                output = run_hook_injection(workspace, target=args.target, max_entries=limit)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                sys.exit(2)
            if not output.strip():
                print("No shared context records found. Run `agent-bridge record` first.",
                      file=sys.stderr)
                sys.exit(0)
            print(output)
        else:
            hooks_parser.print_help()
            sys.exit(0)


if __name__ == "__main__":
    main()
