# 🌉 Agent Context Bridge (ACB)

[![PyPI version](https://img.shields.io/pypi/v/agent-context-bridge.svg)](https://pypi.org/project/agent-context-bridge/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![CI](https://github.com/shenn667/agent-context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/shenn667/agent-context-bridge/actions/workflows/ci.yml)

> **Universal, zero-dependency context & memory bridge for autonomous coding agents.**  
> Seamlessly share project decisions, architectural constraints, and task progress between **Hermes Agent**, **Claude Code**, **OpenCode**, and **Codex**.

> ⏱️ **The 10-second version:** every AI coding tool starts blind — decisions made in one agent are lost to the next. ACB records them once (`acb record`) and replays them in each agent's native format (`acb inject`).

![ACB demo: init → record → inject](docs/demo.gif)

*50s, no audio: `init` → `record` → `list` → `inject` for Claude & Hermes. One store (`.agent_bridge/`) → every agent.*

---

## 💡 The Problem: Multi-Agent Context Fragmentation

When switching between modern AI developer tools (e.g., Claude Code in terminal, Hermes swarm running in background, OpenCode in IDE):
1. **Each agent starts blind**: Context learned by one agent in a prior turn is lost to the next.
2. **Token waste**: Agents re-read entire repository trees to rediscover decisions already made.
3. **No persistent audit trail**: Critical architectural choices disappear with session resets.

**Agent Context Bridge** solves this with a lightweight, file-backed offline store (`.agent_bridge/`) and dedicated adapter templates for each agent's native prompt hook format.

---

## ✨ Features

- **Zero Runtime Dependencies**: Pure Python standard library (`argparse`, `json`, `dataclasses`, `datetime`). Fast and crash-resilient.
- **Offline & Local-First**: No background daemon, no external database, no network calls. Works 100% offline.
- **Multi-Agent Adapters**: Native formatters for **Hermes Agent**, **Claude Code**, **OpenCode**, and **Codex**.
- **Human-Readable & Machine-Parseable**: Automatically maintains both `records.jsonl` (structured) and `SHARED_CONTEXT.md` (markdown view).
- **Fast CLI**: Simple `agent-bridge` (`acb`) command for CI, shell hooks, or direct agent execution.

---

## 📦 Installation

```bash
pip install agent-context-bridge
```

Or install locally from source:

```bash
git clone https://github.com/shenn667/agent-context-bridge.git
cd agent-context-bridge
pip install -e .
```

---

## 🚀 Quickstart

### 1. Initialize a Workspace

```bash
acb init
```
Creates `.agent_bridge/records.jsonl` and `.agent_bridge/SHARED_CONTEXT.md`.

### 2. Record a Context Decision

```bash
acb record \
  --agent hermes-dev \
  --topic "Database Engine" \
  --summary "Adopted SQLite WAL mode for local agent state storage" \
  --details "PostgreSQL required Docker containers; SQLite provides zero-latency offline access." \
  --tag db --tag architecture
```

### 3. List Shared Context

```bash
acb list
```

### 4. Inject Context into an Agent Session

Output prompt-ready context tailored for your target agent:

```bash
# For Claude Code SessionStart hook:
acb inject --target claude

# For Hermes Agent system context:
acb inject --target hermes

# For OpenCode:
acb inject --target opencode
```

---

## ✅ Demo locale (3 commandes)

Reproductible depuis une clone fraîche — prouve install + record/inject + version cohérente :

```bash
pip install -e .
acb init --dir /tmp/acb-demo && acb record --dir /tmp/acb-demo --agent hermes-dev --topic "Demo" --summary "Bridge OK" && acb inject --dir /tmp/acb-demo --target hermes
acb --version
```

Attendu : `agent-bridge 0.2.0` (identique à `pyproject.toml`, `__init__.__version__` et au tag `v0.2.0` — le workflow `release.yml` refuse la publication si tag ≠ version).

---

## 🪝 Hooks natifs (1 commande chacun)

### Claude Code — SessionStart

```bash
acb hooks claude --print     # affiche le snippet .claude/settings.json
acb hooks claude --install   # écrit/fusionne <workspace>/.claude/settings.json (idempotent)
echo '{}' | acb hooks run --target claude   # teste le hook : exit 0 + contexte sur stdout
```

Le hook enregistré est `acb inject --target claude` : Claude Code l'exécute à chaque
SessionStart (payload JSON sur stdin, ignoré) et le stdout est injecté en contexte de session.

### Hermes Agent — inject

```bash
acb hooks hermes --print     # snippet de câblage (préambule de session)
acb inject --target hermes   # inject 1-commande, prêt pour le system context
```

---

## 🏗️ Architecture

```
                      ┌──────────────────────┐
                      │  Your Project Repo   │
                      └──────────┬───────────┘
                                 │
                     .agent_bridge/SHARED_CONTEXT.md
                     .agent_bridge/records.jsonl
                                 │
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
     ┌───────────┐         ┌───────────┐         ┌───────────┐
     │  Hermes   │         │Claude Code│         │ OpenCode  │
     │  Adapter  │         │  Adapter  │         │  Adapter  │
     └───────────┘         └───────────┘         └───────────┘
```

---

## 🧪 Running Tests

```bash
pytest -v
```

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).  
Authored by **shenn667** ([lehdev@yandex.com](mailto:lehdev@yandex.com)).
