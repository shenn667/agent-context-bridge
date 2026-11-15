"""Tests for command-line interface."""

import subprocess
import sys
from pathlib import Path


def test_cli_execution(tmp_path: Path):
    cmd_base = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(tmp_path)]
    env = {"PYTHONPATH": str(Path(__file__).parent.parent / "src")}

    # init
    res = subprocess.run([*cmd_base, "init"], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "Initialized Agent Context Bridge" in res.stdout

    # record
    res = subprocess.run([
        *cmd_base, "record",
        "--agent", "security",
        "--topic", "Auth Gate",
        "--summary", "Enforced JWT bearer token validation.",
    ], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "Recorded [security] Auth Gate" in res.stdout

    # list
    res = subprocess.run([*cmd_base, "list"], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "Enforced JWT bearer token validation." in res.stdout

    # inject
    res = subprocess.run([*cmd_base, "inject", "--target", "claude"], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "Claude Code Integration" in res.stdout

    # export
    res = subprocess.run([*cmd_base, "export"], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert '"total_tokens":' in res.stdout
