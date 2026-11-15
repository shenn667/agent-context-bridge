"""Tests for --version coherence and native hooks (dev t_6b110bf3)."""

import json
import re
import subprocess
import sys
from pathlib import Path

import agent_context_bridge
from agent_context_bridge import get_version
from agent_context_bridge.hooks import (
    claude_settings_fragment,
    hook_command,
    install_claude_hook,
    render_claude_settings_snippet,
    run_hook_injection,
)

SRC_DIR = Path(__file__).parent.parent / "src"
REPO_ROOT = Path(__file__).parent.parent


def _run_cli(args, workspace: Path, stdin_text=None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(workspace), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=stdin_text,
        env={"PYTHONPATH": str(SRC_DIR)},
    )


def test_version_coherent_with_pyproject_and_init():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    assert m, "version not found in pyproject.toml"
    assert m.group(1) == agent_context_bridge.__version__ == get_version()


def test_cli_version_flag(tmp_path: Path):
    res = _run_cli(["--version"], tmp_path)
    assert res.returncode == 0
    assert get_version() in res.stdout


def test_hooks_claude_print_is_valid_settings_json(tmp_path: Path):
    res = _run_cli(["hooks", "claude", "--print"], tmp_path)
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    starts = data["hooks"]["SessionStart"]
    assert starts[0]["hooks"][0]["type"] == "command"
    assert "acb inject --target claude" in starts[0]["hooks"][0]["command"]


def test_hooks_claude_install_idempotent_merge(tmp_path: Path):
    res = _run_cli(["hooks", "claude", "--install"], tmp_path)
    assert res.returncode == 0, res.stderr
    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    first = json.loads(settings.read_text())

    # pre-existing keys preserved + second install does not duplicate
    res2 = _run_cli(["hooks", "claude", "--install"], tmp_path)
    assert res2.returncode == 0, res2.stderr
    second = json.loads(settings.read_text())
    assert first == second
    cmds = [
        h.get("command")
        for entry in second["hooks"]["SessionStart"]
        for h in entry.get("hooks", [])
    ]
    assert cmds.count(hook_command("claude")) == 1


def test_hooks_run_drains_stdin_and_injects(tmp_path: Path):
    assert _run_cli(["init"], tmp_path).returncode == 0
    assert _run_cli(
        ["record", "--agent", "hermes-dev", "--topic", "Hooks",
         "--summary", "SessionStart wiring verified."], tmp_path
    ).returncode == 0

    for target, marker in (
        ("hermes", "HERMES MULTI-AGENT SHARED MEMORY"),
        ("claude", "Claude Code Integration"),
    ):
        res = _run_cli(["hooks", "run", "--target", target], tmp_path, stdin_text='{"session_id":"abc"}')
        assert res.returncode == 0, res.stderr
        assert marker in res.stdout
        assert "SessionStart wiring verified." in res.stdout


def test_hooks_run_empty_store_exits_zero(tmp_path: Path):
    assert _run_cli(["init"], tmp_path).returncode == 0
    res = _run_cli(["hooks", "run", "--target", "hermes"], tmp_path, stdin_text="{}")
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_hooks_helpers_pure(tmp_path: Path):
    frag = claude_settings_fragment()
    assert frag["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "acb inject --target claude"
    assert json.loads(render_claude_settings_snippet()) == frag
    assert install_claude_hook(tmp_path).name == "settings.json"
    assert run_hook_injection(tmp_path, target="hermes") == ""
