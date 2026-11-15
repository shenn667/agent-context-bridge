"""Agent Context Bridge (ACB)

Universal, zero-dependency context & memory bridge for multi-agent workflows.
Enables transparent context handoff between Hermes Agent, Claude Code, OpenCode, and Codex.
"""

__version__ = "0.1.0"
__author__ = "shenn667"

from agent_context_bridge.core import (
    ContextRecord,
    MemoryStore,
    BridgeSnapshot,
)
from agent_context_bridge.adapters import (
    HermesAdapter,
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    CodexAdapter,
)

__all__ = [
    "ContextRecord",
    "MemoryStore",
    "BridgeSnapshot",
    "HermesAdapter",
    "ClaudeCodeAdapter",
    "OpenCodeAdapter",
    "CodexAdapter",
]
