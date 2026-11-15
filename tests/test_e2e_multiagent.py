"""E2E multi-agent test: record -> inject for hermes/claude/opencode/codex.

Covers the QA acceptance criteria:
- full CLI round-trip init -> record (x4 agents) -> inject (x4 targets)
- records.jsonl + SHARED_CONTEXT.md coherence (same items, valid JSONL)
- README links hygiene: no dead/placeholder badge or link (CI fails otherwise)
"""

import json
import re
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src"
REPO_ROOT = Path(__file__).parent.parent

AGENTS = ["hermes", "claude", "opencode", "codex"]
TARGETS = ["hermes", "claude", "opencode", "codex"]
TARGET_MARKERS = {
    "hermes": "HERMES MULTI-AGENT SHARED MEMORY",
    "claude": "Claude Code Integration",
    "opencode": "[OpenCode Shared Context]",
    "codex": "Codex Multi-Agent Shared State",
}


def _run_cli(args, workspace: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "agent_context_bridge.cli", "--dir", str(workspace), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SRC_DIR)},
    )


def test_e2e_record_inject_all_targets(tmp_path: Path):
    """Record one item per agent via CLI, inject per target, check coherence."""
    res = _run_cli(["init"], tmp_path)
    assert res.returncode == 0, res.stderr

    summaries = {}
    for agent in AGENTS:
        summary = f"E2E decision recorded by {agent}."
        summaries[agent] = summary
        res = _run_cli(
            [
                "record",
                "--agent", agent,
                "--topic", f"E2E {agent} topic",
                "--summary", summary,
                "--tag", "e2e",
            ],
            tmp_path,
        )
        assert res.returncode == 0, res.stderr
        assert f"Recorded [{agent}]" in res.stdout

    # 1. records.jsonl: 4 valid JSON lines with required keys
    records_file = tmp_path / ".agent_bridge" / "records.jsonl"
    assert records_file.exists()
    lines = [ln for ln in records_file.read_text().splitlines() if ln.strip()]
    assert len(lines) == 4, f"expected 4 records, got {len(lines)}"
    records = [json.loads(ln) for ln in lines]  # raises if a line is corrupt
    for rec in records:
        for key in ("agent", "topic", "summary", "timestamp"):
            assert key in rec, f"missing key {key!r} in {rec}"
    recorded_agents = {r["agent"] for r in records}
    assert recorded_agents == set(AGENTS), recorded_agents

    # 2. SHARED_CONTEXT.md coherent: every topic+summary present
    md_file = tmp_path / ".agent_bridge" / "SHARED_CONTEXT.md"
    assert md_file.exists()
    md = md_file.read_text()
    for agent in AGENTS:
        assert f"E2E {agent} topic" in md, f"topic for {agent} missing in SHARED_CONTEXT.md"
        assert summaries[agent] in md, f"summary for {agent} missing in SHARED_CONTEXT.md"

    # 3. inject per target: each adapter output carries all 4 summaries
    for target in TARGETS:
        res = _run_cli(["inject", "--target", target], tmp_path)
        assert res.returncode == 0, res.stderr
        assert TARGET_MARKERS[target] in res.stdout, f"marker missing for {target}"
        for agent in AGENTS:
            assert summaries[agent] in res.stdout, (
                f"summary of {agent} missing in inject --target {target}"
            )


def test_readme_links_not_dead():
    """CI guard: README must not contain dead/placeholder badge or link.

    Offline-safe (no network): rejects empty URLs, placeholders, and a CI
    badge that does not point at the repo's real GitHub Actions page.
    """
    readme = (REPO_ROOT / "README.md").read_text()
    urls = re.findall(r"https?://[^\s\)\"'<>]+", readme)
    assert urls, "README contains no links at all"

    placeholders = ("example.com", "TODO", "your-username", "your_repo", "localhost")
    for url in urls:
        clean = url.rstrip(".,;")
        for ph in placeholders:
            assert ph not in clean, f"placeholder link in README: {clean}"

    # CI badge link must target this repo's real Actions (generic /actions
    # page accepted; workflow-scoped badge recommended, flagged to dev).
    repo_actions = "github.com/shenn667/agent-context-bridge/actions"
    badge_targets = re.findall(r"\]\((https?://[^\)]+)\)", readme)
    ci_links = [u for u in badge_targets if "actions" in u or "CI" in readme]
    assert any(repo_actions in u for u in badge_targets), (
        f"no README badge/link points to the repo's real GitHub Actions: {badge_targets}"
    )
