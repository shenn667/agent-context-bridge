"""Agent Context Bridge (ACB)

Universal, zero-dependency context & memory bridge for multi-agent workflows.
Enables transparent context handoff between Hermes Agent, Claude Code, OpenCode, and Codex.
"""

__version__ = "0.3.0"
__author__ = "shenn667"


def get_version() -> str:
    """Single source of truth for the package version.

    Prefers installed dist metadata (correct after ``pip install`` even if
    the source tree was bumped), falls back to ``__version__`` for
    source-tree / editable edge cases. Zero-dependency (stdlib only).
    """
    try:
        from importlib.metadata import version, PackageNotFoundError

        try:
            return version("agent-context-bridge")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    return __version__

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
    "get_version",
]
