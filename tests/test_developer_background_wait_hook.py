"""
Regression tests for ticket #93: the `developer` subagent (phase=implement,
and CI-red repair rounds) can background the verification test run via
Bash(run_in_background: true) and then end its own turn to "resume once it
completes" — but a subagent's turn ending TERMINATES it, it is never
suspended and resumed. The harness kills the background process, and the
outer process reports a hollow "success" with no real verification result.
This was already forbidden in prose (agents/developer.md's pre-existing
Hard Rule "Never end a turn while a command you backgrounded is still
running"), but the incident happened anyway — prose alone was not reliable
enough, so a mechanical backstop is added: a SubagentStop hook
(hooks/check-developer-background-wait.mjs) that inspects the developer's
own transcript and blocks the stop when a backgrounded Bash call has no
later Monitor call resolving it.

Behavioural requirements:
  BR1 - the hook script exists and is wired into hooks/hooks.json under
        SubagentStop with matcher "developer".
  BR2 - executable: the hook blocks when the transcript shows an unresolved
        Bash(run_in_background: true) call (started, never Monitor-ed).
  BR3 - executable: the hook does NOT block when a Monitor call follows the
        backgrounded Bash call (the sanctioned in-turn wait).
  BR4 - executable: the hook ignores agents other than "developer" (e.g. a
        "reviewer" dispatch with the same unresolved pattern is untouched).
  BR5 - fail-safe: malformed stdin / missing transcript path never blocks.
  BR6 - agents/developer.md's Hard Rule names the ticket #93 anti-pattern
        phrase and the mechanical hook, so the two stay discoverable
        together.
  BR7 - AGENTS.md documents the cross-file invariant between the hook and
        the Hard Rule.
  BR8 - the new hook reference is discovered by the existing
        ${CLAUDE_PLUGIN_ROOT} release-payload scanner (tools/check_plugin_payload.py),
        so it ships on a marketplace install like check-mcp-availability.mjs
        already does.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

import tools.check_plugin_payload as cpp

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "check-developer-background-wait.mjs"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# BR1 - hook exists and is wired into hooks.json
# ---------------------------------------------------------------------------


def test_hook_script_exists():
    assert HOOK_PATH.exists(), (
        f"{HOOK_PATH} does not exist. The ticket #93 mechanical backstop "
        "hook must be created."
    )


def test_hook_wired_in_hooks_json():
    config = json.loads(_read(HOOKS_JSON))
    subagent_stop = config.get("hooks", {}).get("SubagentStop", [])
    matchers = {entry.get("matcher"): entry for entry in subagent_stop}
    assert "developer" in matchers, (
        "hooks/hooks.json must register a SubagentStop entry with "
        'matcher "developer".'
    )
    commands = [
        h.get("command", "")
        for h in matchers["developer"].get("hooks", [])
    ]
    assert any("check-developer-background-wait.mjs" in c for c in commands), (
        'hooks/hooks.json "developer" SubagentStop entry must invoke '
        "hooks/check-developer-background-wait.mjs."
    )
    # The pre-existing context-extractor hook must still be present —
    # this change must not have clobbered it.
    assert "context-extractor" in matchers, (
        "hooks/hooks.json lost its pre-existing context-extractor "
        "SubagentStop entry."
    )


def test_hook_node_check():
    """Optional: run 'node --check' to verify syntax. Skips gracefully if
    node is not on PATH."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH — skipping syntax check")
    result = subprocess.run(
        [node, "--check", str(HOOK_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check hooks/check-developer-background-wait.mjs failed "
        f"(exit {result.returncode}):\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Executable behaviour — synthetic transcripts
# ---------------------------------------------------------------------------


def _tool_use_line(name: str, input_: dict) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": input_}],
        }
    )


def _run_hook(tmp_path: pathlib.Path, agent_type: str, transcript_lines: list[str]):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH — skipping executable hook test")

    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text("\n".join(transcript_lines) + "\n", encoding="utf-8")

    payload = {
        "agent_type": agent_type,
        "agent_transcript_path": str(transcript_path),
    }
    result = subprocess.run(
        [node, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return result


def test_hook_blocks_unresolved_background_verification_run(tmp_path):
    """
    REGRESSION (#93): the exact incident shape — the developer starts the
    verification suite via Bash(run_in_background: true) and the transcript
    ends there, with no Monitor call ever resolving it.
    """
    lines = [
        _tool_use_line(
            "Bash",
            {
                "command": "nohup pwsh -File scripts/test.ps1 > test-run.log 2>&1 &",
                "run_in_background": True,
            },
        ),
    ]
    result = _run_hook(tmp_path, "agent-autonomous-developer:developer", lines)
    assert result.returncode == 0
    assert result.stdout.strip(), (
        "expected a block decision on stdout for an unresolved backgrounded "
        f"verification run; got empty stdout. stderr: {result.stderr!r}"
    )
    decision = json.loads(result.stdout)
    assert decision.get("decision") == "block"
    assert "reason" in decision and decision["reason"]


def test_hook_still_blocks_when_a_monitor_was_armed(tmp_path):
    """
    REGRESSION (agent-worktree#176 attempt 1, ticket #101): background the
    full-suite run, arm a Monitor, end the turn. Until #101 this was "the
    sanctioned pattern" and passed the hook — and the session died, because
    nothing wakes a headless process. A Monitor resolves nothing.
    """
    lines = [
        _tool_use_line(
            "Bash",
            {
                "command": "nohup pwsh -File scripts/test.ps1 > test-run.log 2>&1 &",
                "run_in_background": True,
            },
        ),
        _tool_use_line("Monitor", {"path": "test-run.log", "until": "EXIT_CODE="}),
    ]
    result = _run_hook(tmp_path, "agent-autonomous-developer:developer", lines)
    assert result.returncode == 0
    assert result.stdout.strip(), (
        "expected a block: a Monitor after a backgrounded run is the exact "
        f"shape #176 died on; got: {result.stdout!r}"
    )
    assert json.loads(result.stdout).get("decision") == "block"


def test_hook_passes_when_the_pretooluse_hook_refused_the_call(tmp_path):
    """A backgrounded call that hooks/check-no-background.mjs refused never
    ran; blocking the stop would trap the agent behind a call it cannot undo."""
    lines = [
        _tool_use_line(
            "Bash",
            {"command": "nohup npm test > out.log 2>&1 &", "run_in_background": True},
        ),
        json.dumps(
            {
                "type": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "is_error": True,
                        "content": "[adev-no-background] refused Bash(run_in_background: true): …",
                    }
                ],
            }
        ),
    ]
    result = _run_hook(tmp_path, "agent-autonomous-developer:developer", lines)
    assert result.returncode == 0
    assert result.stdout.strip() == "", f"expected no block; got: {result.stdout!r}"


def test_hook_never_blocks_twice(tmp_path):
    lines = [
        _tool_use_line("Bash", {"command": "npm test &", "run_in_background": True}),
    ]
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "agent_type": "agent-autonomous-developer:developer",
        "agent_transcript_path": str(transcript),
        "stop_hook_active": True,
    }
    result = subprocess.run([node, str(HOOK_PATH)], input=json.dumps(payload), capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_ignores_non_developer_agents(tmp_path):
    """
    The same unresolved pattern from a different agent (e.g. "reviewer")
    must not trigger this hook — it is scoped to the developer agent only.
    """
    lines = [
        _tool_use_line(
            "Bash",
            {"command": "nohup npm test > out.log 2>&1 &", "run_in_background": True},
        ),
    ]
    result = _run_hook(tmp_path, "agent-autonomous-developer:reviewer", lines)
    assert result.returncode == 0
    assert result.stdout.strip() == "", (
        f"hook must not activate for a non-developer agent_type; got: {result.stdout!r}"
    )


def test_hook_fail_safe_on_malformed_stdin():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH — skipping executable hook test")
    result = subprocess.run(
        [node, str(HOOK_PATH)],
        input="not json",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_fail_safe_on_missing_transcript(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH — skipping executable hook test")
    payload = {
        "agent_type": "agent-autonomous-developer:developer",
        "agent_transcript_path": str(tmp_path / "does-not-exist.jsonl"),
    }
    result = subprocess.run(
        [node, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# BR6 - agents/developer.md names the anti-pattern and the hook
# ---------------------------------------------------------------------------


def test_developer_md_names_ticket_93_incident_and_hook():
    text = _read(DEVELOPER_MD)
    assert "#93" in text, (
        "agents/developer.md must reference ticket #93 in the "
        "background-wait Hard Rule."
    )
    assert "I'll resume once it completes" in text, (
        "agents/developer.md must quote the exact anti-pattern phrase from "
        "the #93 incident so it is recognizable as forbidden."
    )
    assert "check-developer-background-wait.mjs" in text, (
        "agents/developer.md must reference the mechanical backstop hook "
        "hooks/check-developer-background-wait.mjs."
    )


# ---------------------------------------------------------------------------
# BR7 - AGENTS.md documents the cross-file invariant
# ---------------------------------------------------------------------------


def test_agents_md_documents_the_backstop_invariant():
    text = _read(AGENTS_MD)
    assert "#93" in text
    assert "check-developer-background-wait.mjs" in text
    assert "hooks.json" in text


# ---------------------------------------------------------------------------
# BR8 - the new hook is discovered by the release-payload scanner
# ---------------------------------------------------------------------------


def test_release_payload_scanner_discovers_new_hook_reference():
    references = cpp.discover_references(REPO_ROOT)
    assert any(
        r.path == "hooks/check-developer-background-wait.mjs"
        and r.source_file == "hooks/hooks.json"
        for r in references
    ), (
        "tools/check_plugin_payload.py's discover_references() must find "
        "the new hooks/check-developer-background-wait.mjs reference in "
        "hooks/hooks.json, so release.yml's payload gate covers it the same "
        "way it already covers hooks/check-mcp-availability.mjs."
    )
