"""
Regression tests for ticket #35: context-extractor MCP failsafe.

When agent-project-issues MCP tools are unavailable the pipeline must abort
loudly rather than silently producing a branch-name-derived context summary.

Two-layer failsafe:
  1. SubagentStop hook (hooks/check-mcp-availability.mjs) — primary, deterministic.
  2. Hard Rule in agents/context-extractor.md — secondary guard.

Red→green anchor: Group 1 and Group 3 tests fail against the unfixed code and
pass after the implementation is in place.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

CONTEXT_EXTRACTOR_MD = REPO_ROOT / "agents" / "context-extractor.md"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
HOOKS_MJS = REPO_ROOT / "hooks" / "check-mcp-availability.mjs"
PROCESS_TICKET_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

NODE_AVAILABLE = shutil.which("node") is not None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_hard_rules_block(text: str) -> str:
    """Return the text of the '## Hard rules' section."""
    m = re.search(r"## Hard rules(.*?)(?=\n## |\Z)", text, re.DOTALL | re.IGNORECASE)
    assert m, "agents/context-extractor.md must contain a '## Hard rules' section"
    return m.group(1)


# ---------------------------------------------------------------------------
# Group 1 — Hard Rule regression (red→green anchor)
# ---------------------------------------------------------------------------

def test_hard_rule_stops_on_mcp_unavailable():
    """
    REGRESSION (#35): agents/context-extractor.md Hard Rules block must
    instruct the agent to stop when MCP tools return 'No such tool available',
    must forbid branch-name inference, and must cite /reload-plugins.
    """
    text = _read(CONTEXT_EXTRACTOR_MD)
    hard_rules = _extract_hard_rules_block(text)

    # Must reference the exact error string so the agent recognises it.
    assert "No such tool available" in hard_rules, (
        "Hard Rules block must contain the string 'No such tool available'"
    )

    # Must explicitly forbid branch-name inference.
    lower = hard_rules.lower()
    assert "branch name" in lower, (
        "Hard Rules block must mention 'branch name' (to forbid inferring from it)"
    )
    # Prohibition must be nearby — simple check that both 'branch name' and a
    # negation word appear somewhere in the block.
    has_negation = any(kw in lower for kw in ("never", "do not", "don't", "must not"))
    assert has_negation, (
        "Hard Rules block must contain a negation ('never', 'do not', etc.) "
        "near the branch-name prohibition"
    )

    # Must cite the remediation action.
    assert "/reload-plugins" in hard_rules, (
        "Hard Rules block must cite '/reload-plugins' as the remediation action"
    )


# ---------------------------------------------------------------------------
# Group 2 — hooks/hooks.json structure
# ---------------------------------------------------------------------------

def test_hooks_mjs_exists():
    """hooks/check-mcp-availability.mjs must exist."""
    assert HOOKS_MJS.exists(), (
        f"{HOOKS_MJS} does not exist — create hooks/check-mcp-availability.mjs"
    )


def test_hooks_json_is_valid_json():
    """hooks/hooks.json must be valid JSON."""
    assert HOOKS_JSON.exists(), f"{HOOKS_JSON} does not exist"
    try:
        json.loads(_read(HOOKS_JSON))
    except json.JSONDecodeError as exc:
        pytest.fail(f"hooks/hooks.json is not valid JSON: {exc}")


def test_hooks_json_subagent_stop_event():
    """hooks/hooks.json top-level 'hooks' object must have key 'SubagentStop'."""
    data = json.loads(_read(HOOKS_JSON))
    hooks = data.get("hooks", {})
    assert "SubagentStop" in hooks, (
        "hooks/hooks.json must have a 'SubagentStop' key inside the 'hooks' object"
    )


def test_hooks_json_matcher_context_extractor():
    """A SubagentStop entry must have matcher == 'context-extractor'."""
    data = json.loads(_read(HOOKS_JSON))
    entries = data["hooks"]["SubagentStop"]
    matchers = [e.get("matcher", "") for e in entries]
    assert "context-extractor" in matchers, (
        "hooks/hooks.json SubagentStop must have an entry with "
        "matcher == 'context-extractor'"
    )


def test_hooks_json_command_invokes_mjs():
    """The nested hook entry must be type 'command' and invoke check-mcp-availability.mjs."""
    data = json.loads(_read(HOOKS_JSON))
    entries = data["hooks"]["SubagentStop"]
    for entry in entries:
        if entry.get("matcher") == "context-extractor":
            nested = entry.get("hooks", [])
            assert nested, "SubagentStop entry for context-extractor must have nested hooks"
            cmd_hooks = [h for h in nested if h.get("type") == "command"]
            assert cmd_hooks, (
                "SubagentStop entry for context-extractor must have a hook with "
                "type == 'command'"
            )
            commands = [h.get("command", "") for h in cmd_hooks]
            assert any("check-mcp-availability.mjs" in c for c in commands), (
                "The command hook must reference 'check-mcp-availability.mjs'"
            )
            return
    pytest.fail("No SubagentStop entry with matcher 'context-extractor' found")


# ---------------------------------------------------------------------------
# Group 3 — Hook script behavior (Node subprocess; regression anchor)
# ---------------------------------------------------------------------------

def _make_transcript_line(tool_name: str, content: str, is_error: bool = False) -> str:
    """Return a single JSONL line simulating a transcript tool_result entry."""
    if is_error:
        return json.dumps({
            "type": "tool_result",
            "tool_use_id": "tu_001",
            "tool_name": tool_name,
            "is_error": True,
            "content": content,
        })
    return json.dumps({
        "type": "tool_result",
        "tool_use_id": "tu_001",
        "tool_name": tool_name,
        "is_error": False,
        "content": content,
    })


def _run_hook(tmp_path: pathlib.Path, transcript_lines: list[str], agent_type: str = "context-extractor",
              transcript_path_override=None, stdin_override=None) -> subprocess.CompletedProcess:
    """Write a fake JSONL transcript and invoke the hook script via node."""
    transcript_file = tmp_path / "transcript.jsonl"
    transcript_file.write_text("\n".join(transcript_lines), encoding="utf-8")

    if transcript_path_override is not None:
        t_path = transcript_path_override
    else:
        t_path = str(transcript_file)

    payload = {
        "agent_type": agent_type,
        "agent_transcript_path": t_path,
        "stop_hook_active": False,
        "cwd": str(tmp_path),
    }
    stdin_bytes = (stdin_override if stdin_override is not None
                   else json.dumps(payload).encode())

    return subprocess.run(
        ["node", str(HOOKS_MJS)],
        input=stdin_bytes,
        capture_output=True,
        timeout=15,
    )


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
def test_hook_blocks_when_get_ticket_fails_with_no_such_tool(tmp_path):
    """
    REGRESSION (#35): when the transcript contains a get_ticket call whose
    result is 'No such tool available' and no successful get_ticket, the hook
    must output JSON with decision=='block' and reason mentioning /reload-plugins.
    """
    lines = [
        _make_transcript_line("get_ticket", "No such tool available", is_error=True),
    ]
    result = _run_hook(tmp_path, lines)
    assert result.returncode == 0, (
        f"Hook exited with {result.returncode}; stderr: {result.stderr.decode()}"
    )
    stdout = result.stdout.decode().strip()
    assert stdout, (
        "Hook must write JSON to stdout when blocking; got empty output. "
        f"stderr: {result.stderr.decode()}"
    )
    try:
        decision = json.loads(stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Hook stdout is not valid JSON: {stdout!r}")

    assert decision.get("decision") == "block", (
        f"Expected decision=='block', got {decision!r}"
    )
    reason = decision.get("reason", "")
    assert "/reload-plugins" in reason, (
        f"Reason must mention '/reload-plugins', got: {reason!r}"
    )


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
def test_hook_does_not_block_on_successful_run(tmp_path):
    """When the transcript has a successful get_ticket result, the hook must not block."""
    lines = [
        _make_transcript_line("get_ticket", '{"id": 42, "title": "Fix the thing"}'),
    ]
    result = _run_hook(tmp_path, lines)
    assert result.returncode == 0
    stdout = result.stdout.decode().strip()
    if stdout:
        # If anything is output, it must NOT be a block decision.
        try:
            decision = json.loads(stdout)
            assert decision.get("decision") != "block", (
                f"Hook must not block on a successful run, got: {decision!r}"
            )
        except json.JSONDecodeError:
            pass  # Non-JSON output on a passing run is fine (e.g. empty).


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
def test_hook_does_not_block_when_agent_type_is_wrong(tmp_path):
    """When agent_type is not 'context-extractor', the hook must exit 0 silently."""
    lines = [
        _make_transcript_line("get_ticket", "No such tool available", is_error=True),
    ]
    result = _run_hook(tmp_path, lines, agent_type="developer")
    assert result.returncode == 0
    stdout = result.stdout.decode().strip()
    # Must not block when agent type doesn't match.
    if stdout:
        try:
            decision = json.loads(stdout)
            assert decision.get("decision") != "block", (
                "Hook must not block when agent_type != 'context-extractor'"
            )
        except json.JSONDecodeError:
            pass


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
def test_hook_does_not_block_on_malformed_stdin(tmp_path):
    """When stdin is not valid JSON, the hook must exit 0 with no block output."""
    result = subprocess.run(
        ["node", str(HOOKS_MJS)],
        input=b"not json at all {{{{",
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"Hook must exit 0 on malformed stdin; got {result.returncode}"
    )
    stdout = result.stdout.decode().strip()
    if stdout:
        try:
            decision = json.loads(stdout)
            assert decision.get("decision") != "block", (
                "Hook must not block on malformed stdin"
            )
        except json.JSONDecodeError:
            pass


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
def test_hook_does_not_block_on_missing_transcript(tmp_path):
    """When transcript path points to a nonexistent file, the hook must exit 0 silently."""
    nonexistent = tmp_path / "no_such_file.jsonl"
    payload = {
        "agent_type": "context-extractor",
        "agent_transcript_path": str(nonexistent),
        "stop_hook_active": False,
    }
    result = subprocess.run(
        ["node", str(HOOKS_MJS)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"Hook must exit 0 when transcript file is missing; got {result.returncode}"
    )
    stdout = result.stdout.decode().strip()
    if stdout:
        try:
            decision = json.loads(stdout)
            assert decision.get("decision") != "block"
        except json.JSONDecodeError:
            pass


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
def test_hook_does_not_block_when_error_text_in_ticket_body_only(tmp_path):
    """
    When a SUCCESSFUL get_ticket result's body text includes 'No such tool available'
    (e.g. describing an error scenario), the hook must NOT block — foundSuccessfulFetch
    takes precedence.
    """
    # Simulate a ticket whose body describes the error string, but the fetch succeeded.
    body_with_error_text = json.dumps({
        "id": 35,
        "title": "Handle MCP failures",
        "body": "When MCP returns 'No such tool available' we should abort.",
    })
    lines = [
        # Successful fetch — content contains the error string in ticket body text.
        _make_transcript_line("get_ticket", body_with_error_text, is_error=False),
    ]
    result = _run_hook(tmp_path, lines)
    assert result.returncode == 0
    stdout = result.stdout.decode().strip()
    if stdout:
        try:
            decision = json.loads(stdout)
            assert decision.get("decision") != "block", (
                "Hook must not block when get_ticket succeeded — even if body "
                f"contains the error string. Got: {decision!r}"
            )
        except json.JSONDecodeError:
            pass


# ---------------------------------------------------------------------------
# Group 5 — Phase 1 note in process-ticket SKILL.md
# ---------------------------------------------------------------------------

def test_process_ticket_phase1_mentions_hook_failure():
    """
    REGRESSION (#35): skills/process-ticket/SKILL.md Phase 1 block must
    mention handling a missing/blocked context summary.
    Keywords: ('hook' or 'MCP') near ('stop' or 'surface').
    """
    text = _read(PROCESS_TICKET_MD)

    # Extract Phase 1 section.
    m = re.search(r"### Phase 1.*?(?=### Phase 2)", text, re.DOTALL | re.IGNORECASE)
    assert m, "SKILL.md must contain a 'Phase 1' section followed by 'Phase 2'"
    phase1 = m.group(0).lower()

    has_hook_or_mcp = "hook" in phase1 or "mcp" in phase1
    has_stop_or_surface = "stop" in phase1 or "surface" in phase1

    assert has_hook_or_mcp and has_stop_or_surface, (
        "skills/process-ticket/SKILL.md Phase 1 block must mention handling a "
        "missing/blocked context_summary — expected ('hook' or 'MCP') AND "
        "('stop' or 'surface') somewhere in the Phase 1 section. "
        f"Found hook/MCP={has_hook_or_mcp}, stop/surface={has_stop_or_surface}."
    )
