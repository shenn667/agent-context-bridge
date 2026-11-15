"""Tests for agent adapters."""

from pathlib import Path
from agent_context_bridge.core import MemoryStore, ContextRecord
from agent_context_bridge.adapters import (
    HermesAdapter,
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    CodexAdapter,
)


def test_adapters_empty_store(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.initialize()

    for adapter in [HermesAdapter(), ClaudeCodeAdapter(), OpenCodeAdapter(), CodexAdapter()]:
        assert adapter.format_prompt_injection(store) == ""


def test_adapters_formatting(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.add_record(ContextRecord(agent="dev", topic="API", summary="Created v1 routes."))

    hermes_inj = HermesAdapter().format_prompt_injection(store)
    assert "HERMES MULTI-AGENT SHARED MEMORY" in hermes_inj
    assert "[dev] **API**: Created v1 routes." in hermes_inj

    claude_inj = ClaudeCodeAdapter().format_prompt_injection(store)
    assert "Claude Code Integration" in claude_inj
    assert "**dev** (API): Created v1 routes." in claude_inj

    opencode_inj = OpenCodeAdapter().format_prompt_injection(store)
    assert "[OpenCode Shared Context]" in opencode_inj

    codex_inj = CodexAdapter().format_prompt_injection(store)
    assert "Codex Multi-Agent Shared State" in codex_inj
