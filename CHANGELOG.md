# Changelog

All notable changes to `agent-context-bridge` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.3.1] - 2026-11-17
### Fixed
- Patch release: version alignment 0.3.1 across `pyproject.toml`,
  `__init__.__version__`, `server.json`, and registry metadata
  (`README.md` mcp-name marker verified, `server.json` present).

## [0.3.0] - 2026-11-16
### Added
- `acb search <query> [-n/--limit 1..100] [--tag]... [--agent] [--json] [--dir]`
  (full-text OR search, newest-first, `--json` payload `results/count/query`).
- `acb status [--json] [--dir]` (records, store bytes, last_updated, targets;
  never creates the store; exit 0, `initialized: false` when absent).
- `acb prune --older-than DAYS | --keep-last N [--tag]... [--dry-run] [--yes] [--json]`
  (only destructive command: interactive confirm, non-TTY refusal without `--yes`,
  regenerates `SHARED_CONTEXT.md`).
- `acb audit [--json] [--dir]` (read-only secrets/PII scan of the store — API keys,
  tokens, emails, private keys; values always masked, exit 1 on findings).
  `acb record` warns on stderr when content matches a secret pattern (never blocks).
- `acb-mcp` stdio JSON-RPC server, strictly read-only: `acb_search`, `acb_status`
  (any other tool, including `prune`, → `Method not found`; bad params → `-32602`).
- `[project.scripts] acb-mcp` entry point; zero new runtime dependencies (stdlib only).
- `acb --version` (single source of truth: installed dist metadata, fallback `__version__`).
- Native hooks: `acb hooks claude --print|--install`, `acb hooks hermes --print`,
  `acb hooks run --target <hermes|claude|opencode|codex>` (stdin drained with 1 MiB cap, exit 0).
- README: 3-command local demo + 1-command hook wiring docs.
### Security
- Store hardening: `.agent_bridge/` created/repaired to `0700`, store files to `0600`.
- MCP server exposes no destructive tool (prune stays CLI-only with confirmation).
### Fixed
- CI badge now reflects the real workflow status (dynamic `ci.yml` badge) instead of a static "passing" shield.

## [0.2.0] - 2026-11-15
### Added
- Automated PyPI release workflow (Trusted Publishing / OIDC, tag `v*` → PyPI).
- Dynamic PyPI version badge in README.
### Fixed
- Package was never published to PyPI despite the badge (first real public release).

## [0.1.0] - 2026-11-15
### Added
- Initial release: file-backed offline context store (`.agent_bridge/` with `records.jsonl` + `SHARED_CONTEXT.md`).
- CLI `acb` / `agent-bridge`: `init`, `record`, `list`, `inject`, `export`.
- Adapters: Hermes, Claude Code (SessionStart hook format), OpenCode, Codex.
- Zero runtime dependencies (stdlib only: `argparse`, `json`, `dataclasses`, `datetime`).
- Test suite (6 tests) + CI matrix Python 3.10–3.12.
- MIT license.
