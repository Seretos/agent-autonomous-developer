"""
Ticket #118: the installed harness refuses standalone `sleep <n>`, and the
skill forbids `Monitor`/background jobs (#101), so Phase 6's escalating
`Bash("sleep 30/60/120/300")` ladder left a package session with no permitted
way to wait for CI. Phase 6 now waits with one blocking foreground
`project-issues wait-pipeline` call and routes its exit codes.

These tests slice SKILL.md structurally (by heading / list item), never by
line number, and pin only what the gate's routing depends on.

  R2 - Phase 6 waits with `wait-pipeline` (--project/--sha/--timeout 540,
       Bash timeout 600000), routes exit codes 0-5, and contains no
       sleep/Monitor; Phase 5 step 4 links the run artefacts.
  R3 - exit 5 (no verdict) and a non-success/non-failure conclusion on the
       exit-4 path never map to green/red; retrigger once (`i`), then blocked.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"


def _skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _section(text: str, heading_prefix: str, level: str = "## ") -> str:
    """Body of the heading starting with `heading_prefix`, up to the next
    heading of the same level."""
    m = re.search(
        r"^" + re.escape(level + heading_prefix) + r".*?$(.*?)(?=^" + re.escape(level) + r"\S|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"heading {level}{heading_prefix!r} not found in SKILL.md"
    return m.group(1)


def _phase6() -> str:
    return _section(_skill(), "Phase 6")


def _exit_bullet(section: str, code: int) -> str:
    """The list item whose head (first 40 chars) names backticked `code`, up
    to the next list item at the same or lower indentation."""
    lines = section.splitlines()
    head = re.compile(r"^([ \t]*)[-*][ \t]+.{0,40}?`" + str(code) + r"`")
    for i, line in enumerate(lines):
        m = head.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        block = [line]
        for nxt in lines[i + 1:]:
            nm = re.match(r"^([ \t]*)[-*][ \t]+", nxt)
            if nm and len(nm.group(1)) <= indent:
                break
            block.append(nxt)
        return "\n".join(block)
    raise AssertionError(f"no list item for exit code `{code}` in Phase 6")


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------


def test_phase6_waits_with_wait_pipeline_call():
    s = _phase6()
    assert "project-issues wait-pipeline" in s
    for flag in ("--project", "--sha", "--timeout 540"):
        assert flag in s, f"Phase 6 wait call is missing {flag}"
    assert "600000" in s, "the wait call needs an explicit Bash timeout of 600000"


def test_phase6_routes_every_exit_code():
    s = _phase6()
    for code in range(6):
        assert re.search(r"`" + str(code) + r"`", s), f"exit code {code} is not routed"


def test_phase6_has_no_sleep_or_monitor():
    s = _phase6()
    assert not re.search(r"\bsleep\b|Start-Sleep|\bMonitor\b", s, re.IGNORECASE)


def test_phase5_body_links_run_artefacts():
    body = _section(_skill(), "Phase 5")
    m = re.search(r"^4\. \*\*Compose the PR body\*\*.*?(?=^5\. )", body, re.MULTILINE | re.DOTALL)
    assert m, "Phase 5 step 4 not found"
    step4 = m.group(0)
    assert "<rundir>" in step4
    assert "adev:event" in step4, "PR body must link this attempt's adev:event comments"


def test_phase6_keeps_round_cap_and_diagnosis_tools():
    s = _phase6()
    assert "45" in s
    for tool in ("list_pipeline_runs", "get_pipeline_run", "get_pipeline_step_log"):
        assert tool in s


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------


def test_exit5_no_verdict_retriggers_once_then_blocked():
    block = _exit_bullet(_phase6(), 5)
    assert "blocked" in block
    assert re.search(r"\burl\b", block, re.IGNORECASE), "blocked text must quote the run URLs"
    assert re.search(r"`i`|\bi\b round", block), "the retrigger is an infrastructure round"
    assert "--allow-empty" in block
    assert "push" in block
    assert "head" in block, "the retrigger must re-read head before waiting again"


def test_exit5_never_routes_to_green_or_red_or_fix_round():
    block = _exit_bullet(_phase6(), 5)
    assert "never" in block.lower()
    assert not re.search(r"post\s+\*{0,2}`?ci-green", block)
    assert not re.search(r"post\s+\*{0,2}`?ci-red", block)


def test_exit4_fallback_classifies_by_conclusion():
    block = _exit_bullet(_phase6(), 4)
    assert "list_pipeline_runs" in block
    assert "success" in block and "failure" in block
    assert re.search(r"no[- ]verdict|`5`", block), "other conclusions must defer to exit 5's handling"
    assert not re.search(r"\bsleep\b", block, re.IGNORECASE)
