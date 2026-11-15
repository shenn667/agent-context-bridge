# Changelog

All notable changes to `agent-context-bridge` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

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
