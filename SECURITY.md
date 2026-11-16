# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please **do not** open a public issue for security reports.
Contact the maintainer directly: <lehdev@yandex.com>.

Include: description, impact, minimal reproduction, and affected version.
We aim to acknowledge within 72h and ship a fix as a patch release.

## Design notes (relevant to review)

- `agent-context-bridge` is fully offline: no network, no daemon, no exfiltration path by design.
- Storage is local flat files under `.agent_bridge/` (`records.jsonl`, `SHARED_CONTEXT.md`); writes are atomic (`os.replace` via temp file).
- CLI `--dir` resolves to an absolute path; the tool only writes inside `<workspace>/.agent_bridge/`.
- Agent-supplied strings (agent/topic/summary/details) are rendered into markdown prompts — consumers should treat injected context as untrusted data, not instructions.

## Posture (v0.3.0, fixes for AUDIT_SECURITY.md)

- **Permissions (M1).** `MemoryStore.initialize()` enforces `0700` on `.agent_bridge/` and `0600` on `records.jsonl` / `SHARED_CONTEXT.md` (explicit `os.chmod`, best-effort), including repair of pre-existing stores. `atomic_write()` enforces `0600` on every file it writes, and `hooks claude --install` enforces `0600` on `.claude/settings.json`. Verified by `tests/test_security_fixes.py` under umask 022.
- **MCP readonly (H1).** The `acb-mcp` server exposes exactly 2 tools (`acb_search`, `acb_status`). Any other `tools/call` name — including `acb_prune`, even with `dry_run:false` — is answered `Method not found` (`-32601`) and never touches the store. `prune` stays CLI-only with interactive confirmation.
- **MCP workspace confinement (H1/bis).** A client-supplied `dir` argument must resolve inside the server `--dir` root; anything outside is rejected with `-32602` without probing the filesystem. Run one `acb-mcp` per workspace you want to expose.
- **Secrets/PII (H2).** Store contents (`records.jsonl`, `SHARED_CONTEXT.md`) are **clear text by design** (local-only, `0600`, git-ignored) — never paste real secrets; they propagate to `export`, `search --json`, and injected prompts. `acb audit` (stdlib patterns only: API keys, tokens, emails, private paths, private keys) scans `records.jsonl` and reports type/count/line only — values are never printed (masked `***`), exit 1 on findings, 0 when clean. `acb record` warns on stderr (types only, non-blocking) when content matches.
