"""Utility helpers for file I/O, token estimation, and formatting."""

import os
import re
import tempfile
from pathlib import Path
from typing import Union


def estimate_tokens(text: str) -> int:
    """Fast, deterministic heuristic token count (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def sanitize_agent_name(name: str) -> str:
    """Normalize agent name to lowercase alphanumeric with hyphens."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "-", name.strip().lower())
    return re.sub(r"-+", "-", cleaned).strip("-") or "agent"


def atomic_write(target_path: Union[str, Path], content: str, encoding: str = "utf-8") -> None:
    """Safely write content to target file atomically using a temporary file."""
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = path.parent

    with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding=encoding) as tf:
        tf.write(content)
        temp_name = tf.name

    os.replace(temp_name, path)
