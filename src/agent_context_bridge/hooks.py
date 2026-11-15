"""Native agent hook helpers for agent-context-bridge (zero-dependency).

Claude Code invokes SessionStart hooks as shell commands receiving a JSON
payload on stdin. ``acb hooks run`` drains that payload (ignored) and prints
the prompt-ready shared context to stdout — which Claude Code appends to the
session context. Same entrypoint serves Hermes (``--target hermes``).

Single-command wiring:

    acb hooks claude --install      # write .claude/settings.json SessionStart hook
    echo '{}' | acb hooks run --target claude   # test the hook (exit 0)
    acb inject --target hermes       # Hermes one-command inject
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

HOOK_TARGETS = ("hermes", "claude", "opencode", "codex")

DEFAULT_MAX_ENTRIES = 5


def hook_command(target: str = "claude", max_entries: int = DEFAULT_MAX_ENTRIES) -> str:
    """Shell command string registered as the agent's session-start hook."""
    if max_entries == DEFAULT_MAX_ENTRIES:
        return f"acb inject --target {target}"
    return f"acb inject --target {target} -n {max_entries}"


def claude_settings_fragment(
    target: str = "claude", max_entries: int = DEFAULT_MAX_ENTRIES
) -> Dict:
    """Return the ``.claude/settings.json`` fragment wiring SessionStart."""
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(target, max_entries),
                        }
                    ],
                }
            ]
        }
    }


def render_claude_settings_snippet(
    target: str = "claude", max_entries: int = DEFAULT_MAX_ENTRIES
) -> str:
    """Pretty JSON snippet the user copies into ``.claude/settings.json``."""
    return json.dumps(claude_settings_fragment(target, max_entries), indent=2)


def hermes_wiring_snippet(
    target: str = "hermes", max_entries: int = DEFAULT_MAX_ENTRIES
) -> str:
    """One-command Hermes wiring snippet (system context / session preamble)."""
    cmd = hook_command(target, max_entries)
    return (
        "# Hermes Agent — shared memory wiring (agent-context-bridge)\n"
        "# Run once per session preamble, or export as HERMES_SESSION_PREAMBLE_CMD:\n"
        f"{cmd}\n"
        "# Output is prompt-ready context between "
        "<!-- HERMES MULTI-AGENT SHARED MEMORY --> markers."
    )


def install_claude_hook(
    workspace: Path,
    target: str = "claude",
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> Path:
    """Install (idempotent merge) the SessionStart hook into settings.json.

    Merges into ``<workspace>/.claude/settings.json`` preserving existing
    keys; appends our hook entry only if the command is not already present.
    Returns the settings file path.
    """
    from agent_context_bridge.utils import atomic_write

    settings_path = Path(workspace).resolve() / ".claude" / "settings.json"
    command = hook_command(target, max_entries)

    existing: Dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (json.JSONDecodeError, OSError, ValueError):
            existing = {}

    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = existing["hooks"] = {}
    starts: List = hooks.setdefault("SessionStart", [])
    if not isinstance(starts, list):
        starts = hooks["SessionStart"] = []

    already = any(
        isinstance(entry, dict)
        and any(
            isinstance(h, dict) and h.get("command") == command
            for h in entry.get("hooks", [])
        )
        for entry in starts
    )
    if not already:
        starts.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": command}],
            }
        )

    atomic_write(settings_path, json.dumps(existing, indent=2) + "\n")
    return settings_path


def run_hook_injection(
    workspace: Path,
    target: str = "hermes",
    max_entries: Optional[int] = DEFAULT_MAX_ENTRIES,
) -> str:
    """Render prompt-ready context for hook execution (pure, testable).

    Returns "" when the store is empty so hook callers can exit 0 silently.
    """
    from agent_context_bridge.adapters import (
        HermesAdapter,
        ClaudeCodeAdapter,
        OpenCodeAdapter,
        CodexAdapter,
    )
    from agent_context_bridge.core import MemoryStore

    adapters = {
        "hermes": HermesAdapter(),
        "claude": ClaudeCodeAdapter(),
        "opencode": OpenCodeAdapter(),
        "codex": CodexAdapter(),
    }
    if target not in adapters:
        raise ValueError(f"unknown hook target {target!r} (expected one of {HOOK_TARGETS}).")
    store = MemoryStore(Path(workspace).resolve())
    try:
        return adapters[target].format_prompt_injection(
            store, max_entries=max_entries if max_entries is not None else DEFAULT_MAX_ENTRIES
        )
    except OSError:
        return ""
