"""Agent-specific adapters to consume and inject shared context."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pathlib import Path

from agent_context_bridge.core import MemoryStore, ContextRecord, MAX_LIST_LIMIT


#: Cap applied to ``max_entries`` in all adapters (documented hardening rule).
MAX_ADAPTER_ENTRIES = MAX_LIST_LIMIT


def _normalize_max_entries(max_entries: int) -> int:
    """Normalize ``max_entries`` for prompt injection.

    Returns 0 when ``max_entries`` is non-positive (callers then render an
    empty string), otherwise the value capped at ``MAX_ADAPTER_ENTRIES``.
    ``None`` falls back to the default of 5.
    """
    if max_entries is None:
        return 5
    if max_entries <= 0:
        return 0
    return min(max_entries, MAX_ADAPTER_ENTRIES)


class BaseAgentAdapter(ABC):
    """Abstract interface for agent context ingestion."""

    @abstractmethod
    def format_prompt_injection(self, store: MemoryStore, max_entries: int = 5) -> str:
        """Render context snippet suitable for prompt or hook injection."""
        pass


class HermesAdapter(BaseAgentAdapter):
    """Adapter for Nous Research Hermes Agent."""

    def format_prompt_injection(self, store: MemoryStore, max_entries: int = 5) -> str:
        max_entries = _normalize_max_entries(max_entries)
        if max_entries <= 0:
            return ""
        records = store.list_records(limit=max_entries)
        if not records:
            return ""
        lines = [
            "<!-- HERMES MULTI-AGENT SHARED MEMORY -->",
            "Here is recent context and decisions from peer agents in this repository:",
        ]
        for r in records:
            lines.append(f"- [{r.agent}] **{r.topic}**: {r.summary}")
        lines.append("<!-- END SHARED MEMORY -->")
        return "\n".join(lines)


class ClaudeCodeAdapter(BaseAgentAdapter):
    """Adapter for Anthropic Claude Code SessionStart hooks."""

    def format_prompt_injection(self, store: MemoryStore, max_entries: int = 5) -> str:
        max_entries = _normalize_max_entries(max_entries)
        if max_entries <= 0:
            return ""
        records = store.list_records(limit=max_entries)
        if not records:
            return ""
        lines = [
            "## Shared Repository Memory (Claude Code Integration)",
            "The following context was captured from peer agents working on this workspace:",
        ]
        for r in records:
            lines.append(f"* **{r.agent}** ({r.topic}): {r.summary}")
        return "\n".join(lines)


class OpenCodeAdapter(BaseAgentAdapter):
    """Adapter for OpenCode System Prompt Transformer."""

    def format_prompt_injection(self, store: MemoryStore, max_entries: int = 5) -> str:
        max_entries = _normalize_max_entries(max_entries)
        if max_entries <= 0:
            return ""
        records = store.list_records(limit=max_entries)
        if not records:
            return ""
        lines = ["[OpenCode Shared Context]"]
        for r in records:
            lines.append(f"• {r.agent}: {r.summary}")
        return "\n".join(lines)


class CodexAdapter(BaseAgentAdapter):
    """Adapter for Codex CLI environments."""

    def format_prompt_injection(self, store: MemoryStore, max_entries: int = 5) -> str:
        max_entries = _normalize_max_entries(max_entries)
        if max_entries <= 0:
            return ""
        records = store.list_records(limit=max_entries)
        if not records:
            return ""
        lines = ["# Codex Multi-Agent Shared State"]
        for r in records:
            lines.append(f"- [{r.agent}] {r.topic}: {r.summary}")
        return "\n".join(lines)
