# 🌉 Agent Context Bridge (ACB)

[![PyPI version](https://img.shields.io/badge/pypi-v0.1.0-blue.svg)](https://pypi.org/project/agent-context-bridge/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![CI: Passing](https://img.shields.io/badge/CI-passing-success.svg)](https://github.com/shenn667/agent-context-bridge/actions)

> **Universal, zero-dependency context & memory bridge for autonomous coding agents.**  
> Seamlessly share project decisions, architectural constraints, and task progress between **Hermes Agent**, **Claude Code**, **OpenCode**, and **Codex**.

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
