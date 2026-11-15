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
