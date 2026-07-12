"""
Regression tests for ticket #62: developer TDD mandate generalized to ALL
ticket types (not just bug/defect), red->green reporting, and the B5
working-directory context-verification safeguard.

Root cause: the pre-rework agents/developer.md only mandated a
red-before-green regression test "for a bug/defect ticket" — feature tickets
had no equivalent test-first mandate, and the change report only had to show
the final green run, not the red->green transition. Wave-based parallel
worktrees also raise a new risk: a developer subagent silently operating in
the wrong worktree/Serena project.

Note: this safeguard is labeled "B5" (not "B4") to avoid colliding with the
wave loop's own B4 clean-checkout gate, documented in
skills/orchestrate-tickets/SKILL.md and AGENTS.md.

Red→green: these tests fail against the pre-rework agents/developer.md
(bug-only test-first mandate, final-green-only change report, no B5 context
check) and pass after the rework.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Group 1 — test-first mandate covers ALL ticket types, not just bug/defect
# ---------------------------------------------------------------------------


def test_test_first_mandate_covers_feature_tickets_too():
    text = _read(DEVELOPER_MD)
    assert re.search(r"(all\s+ticket\s+types|bug\s+AND\s+feature|bug\s+and\s+feature)",
                      text, re.IGNORECASE), (
        "agents/developer.md must generalize the test-first mandate to cover "
        "ALL ticket types (bug AND feature), not just bug/defect tickets"
    )


def test_test_first_mandate_still_requires_red_then_green():
    text = _read(DEVELOPER_MD)
    lower = text.lower()
    assert "red" in lower and "green" in lower, (
        "agents/developer.md must still require confirming red (fails on "
        "unfixed/pre-change code) then green (passes after the change)"
    )


# ---------------------------------------------------------------------------
# Group 2 — change report shows the red->green transition
# ---------------------------------------------------------------------------


def test_change_report_tests_section_requires_red_green_transition():
    text = _read(DEVELOPER_MD)
    assert re.search(r"red.{0,10}(-|→|to)\s*green|red.{0,20}green\s+transition",
                      text, re.IGNORECASE), (
        "agents/developer.md's change-report 'Tests' section must require "
        "showing the red->green transition, not just the final green run"
    )


def test_change_report_requires_both_initial_failing_and_final_green_run():
    text = _read(DEVELOPER_MD)
    assert re.search(r"initial\s+failing\s+run", text, re.IGNORECASE), (
        "agents/developer.md must require the change report to show BOTH the "
        "initial failing run AND the final green run"
    )


# ---------------------------------------------------------------------------
# Group 3 — B5: working-directory / Serena-project context verification
# ---------------------------------------------------------------------------


def test_b5_context_check_before_first_edit():
    text = _read(DEVELOPER_MD)
    assert "git -C" in text and "rev-parse --show-toplevel" in text, (
        "agents/developer.md must document verifying the working-directory "
        "context via 'git -C <worktree> rev-parse --show-toplevel'"
    )
    assert re.search(r"before\s+the\s+first\s+edit", text, re.IGNORECASE), (
        "agents/developer.md must require this context check BEFORE the "
        "first edit"
    )


def test_b5_context_check_before_handoff_for_commit():
    text = _read(DEVELOPER_MD)
    assert re.search(r"before\s+handing\s+off\s+for\s+commit|immediately\s+before.{0,40}commit",
                      text, re.IGNORECASE), (
        "agents/developer.md must require repeating the context check "
        "immediately before handing off for commit"
    )


def test_b5_mentions_active_serena_project_confirmation():
    text = _read(DEVELOPER_MD)
    assert "Serena" in text and "active" in text.lower(), (
        "agents/developer.md must require confirming the active Serena "
        "project as part of the B5 context check"
    )


def test_developer_md_uses_b5_label_not_b4():
    """B4 is reserved for the wave loop's clean-checkout gate (SKILL.md /
    AGENTS.md); developer.md's own working-directory safeguard must use a
    distinct label to avoid a cross-file naming collision."""
    text = _read(DEVELOPER_MD)
    assert "B5" in text, (
        "agents/developer.md must label its working-directory context "
        "safeguard 'B5', not 'B4' (which is reserved for the wave loop's "
        "clean-checkout gate)"
    )
    assert "B4" not in text, (
        "agents/developer.md must not use the 'B4' label — it collides with "
        "the wave loop's clean-checkout gate defined in SKILL.md/AGENTS.md"
    )


# ---------------------------------------------------------------------------
# Group 4 — AGENTS.md documents B5 as a durable invariant
# ---------------------------------------------------------------------------

AGENTS_MD = REPO_ROOT / "AGENTS.md"


def test_agents_md_documents_b5_safeguard():
    text = _read(AGENTS_MD)
    assert re.search(r"\bB5\b", text), (
        "AGENTS.md must document the developer's B5 working-directory/"
        "Serena-project verification safeguard alongside B1-B4"
    )
