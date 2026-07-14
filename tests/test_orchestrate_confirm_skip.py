"""
Regression tests for ticket #73: orchestrate-tickets Phase B must skip its
interactive go-ahead gate BY DEFAULT on trivially "clean" runs, instead of
always presenting an AskUserQuestion confirmation.

Root cause: Phase B unconditionally called AskUserQuestion before launching
the fleet, even for SINGLE mode or a MULTI run with fit.verdict == "good" and
an empty deferred list — stalling unattended /orchestrate runs on a
rubber-stamp confirmation with no real decision to make.

Fix: Phase B now branches on one precise condition. A "clean run" (SINGLE
mode, OR MULTI with fit.verdict == "good" AND deferred empty) proceeds
WITHOUT the interactive AskUserQuestion gate by default — but still prints a
plain, non-interactive status message listing the waves in order (with
branches), so an attended user can see what it did. Every other run
(fit.verdict == "poor", i.e. the Fit Warning path, OR any non-empty
deferred) keeps today's MANDATORY AskUserQuestion gate, unchanged and never
skipped.

Red->green: these tests fail against the pre-fix SKILL.md/AGENTS.md (Phase B
unconditionally gates via AskUserQuestion with no clean-run skip path, and
no cross-file invariant note exists) and pass after the fix.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _phase_b(body: str) -> str:
    match = re.search(
        r"## Phase B.*?(?=\n## Phase C)", body, re.DOTALL
    )
    assert match is not None, "Could not find '## Phase B' section in SKILL.md"
    return match.group(0)


def _agents_confirm_skip_section(text: str) -> str:
    match = re.search(
        r"## Phase B confirmation default-skips on clean runs \(ticket #73\).*?"
        r"(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not find the '## Phase B confirmation default-skips on clean "
        "runs (ticket #73)' section in AGENTS.md"
    )
    return match.group(0)


# ---------------------------------------------------------------------------
# Regression: clean run skips the interactive gate by default
# ---------------------------------------------------------------------------


def test_clean_run_skips_gate_by_default():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)
    assert re.search(r"clean run", phase_b, re.IGNORECASE), (
        "Phase B must define a 'clean run' condition (SINGLE mode, or "
        "good-fit MULTI with empty deferred)"
    )
    assert re.search(
        r"clean run.{0,400}without.{0,120}(AskUserQuestion|interactive.{0,20}gate)",
        phase_b,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B must document that a clean run proceeds WITHOUT the "
        "interactive AskUserQuestion gate by default"
    )
    assert re.search(r"by default", phase_b, re.IGNORECASE), (
        "Phase B must describe the skip as the default behaviour for a "
        "clean run (no flag, no opt-in)"
    )


# ---------------------------------------------------------------------------
# Edge: poor fit keeps the mandatory gate
# ---------------------------------------------------------------------------


def test_poor_fit_gate_stays_mandatory():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)
    assert re.search(
        r"poor.{0,200}mandatory|mandatory.{0,200}poor",
        phase_b,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B must state the interactive gate stays MANDATORY when "
        "fit.verdict == 'poor' (the Fit Warning path)"
    )
    assert re.search(r"never skipped|never skip", phase_b, re.IGNORECASE), (
        "Phase B must state the mandatory cases are never skipped"
    )


# ---------------------------------------------------------------------------
# Edge: non-empty deferred keeps the mandatory gate
# ---------------------------------------------------------------------------


def test_nonempty_deferred_gate_stays_mandatory():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)
    assert re.search(
        r"non-empty.{0,120}deferred.{0,200}mandatory|mandatory.{0,200}non-empty.{0,60}deferred",
        phase_b,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B must state the interactive gate stays MANDATORY when "
        "deferred is non-empty"
    )


# ---------------------------------------------------------------------------
# Skip path still surfaces the plan (waves + branches) non-interactively
# ---------------------------------------------------------------------------


def test_skip_path_still_prints_wave_status_message():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)
    assert re.search(
        r"(status message|non-interactive).{0,300}waves.{0,120}branch",
        phase_b,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B's skip branch must still emit a plain, non-interactive "
        "status message listing the waves (in order, with branches)"
    )


# ---------------------------------------------------------------------------
# Hard rules restate the clean-skip / mandatory-cases / still-prints-plan bullet
# ---------------------------------------------------------------------------


def test_hard_rules_documents_confirm_skip_behavior():
    body = _extract_body(_read(ORCHESTRATE_MD))
    match = re.search(r"## Hard rules.*", body, re.DOTALL)
    assert match is not None, "Could not find '## Hard rules' section in SKILL.md"
    hard_rules = match.group(0)
    assert re.search(r"clean run.{0,200}by default", hard_rules, re.DOTALL | re.IGNORECASE), (
        "Hard rules must restate that the clean case proceeds without the "
        "interactive gate by default"
    )
    assert re.search(r"never skipped|never skip", hard_rules, re.IGNORECASE), (
        "Hard rules must restate that the two mandatory cases (poor fit, "
        "non-empty deferred) are never skipped"
    )
    assert re.search(
        r"status message|non-interactive", hard_rules, re.IGNORECASE
    ), (
        "Hard rules must restate that a skipped gate still prints the "
        "waves+branches status message"
    )


# ---------------------------------------------------------------------------
# Regression (ticket #73 fix-up): item 2 (mandatory-ask branch) must ALSO
# state "dependencies checked, none applied" for the poor-fit-with-empty-
# deferred case, not only item 1's clean-run skip path.
# ---------------------------------------------------------------------------


def test_item2_states_dependencies_checked_when_deferred_empty():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)
    match = re.search(r"2\.\s+\*\*Otherwise.*", phase_b, re.DOTALL)
    assert match is not None, (
        "Could not find item 2 (mandatory go-ahead gate) in Phase B"
    )
    item2 = match.group(0)
    assert re.search(
        r"deferred.{0,80}empty.{0,400}checked and none applied"
        r"|empty.{0,80}deferred.{0,400}checked and none applied",
        item2,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B item 2 (the mandatory-ask branch, which also fires for a "
        "poor-fit run with an EMPTY deferred list) must state plainly that "
        "logical-ordering dependencies were checked and none applied for "
        "the empty-deferred case — otherwise that path silently drops the "
        "statement item 1's clean-run path makes, reintroducing the exact "
        "blind spot this phase exists to prevent"
    )


# ---------------------------------------------------------------------------
# Cross-file invariant documented in AGENTS.md
# ---------------------------------------------------------------------------


def test_agents_md_documents_confirm_skip_invariant():
    text = _read(AGENTS_MD)
    section = _agents_confirm_skip_section(text)
    assert re.search(r"Phase B", section), (
        "AGENTS.md's ticket #73 section must reference Phase B"
    )
    assert re.search(
        r"(default[- ]skip|skip.{0,40}by default).{0,400}(clean|good-fit|SINGLE)",
        section,
        re.DOTALL | re.IGNORECASE,
    ), (
        "AGENTS.md's ticket #73 section must document the "
        "default-skip-on-clean-runs invariant"
    )
    assert re.search(
        r"non-empty.{0,60}deferred|deferred.{0,60}non-empty", section,
        re.IGNORECASE,
    ), (
        "AGENTS.md's ticket #73 section must name the non-empty-deferred "
        "mandatory case"
    )
    assert re.search(r"poor", section, re.IGNORECASE), (
        "AGENTS.md's ticket #73 section must name the poor-fit mandatory case"
    )
    assert re.search(r"mandatory", section, re.IGNORECASE), (
        "AGENTS.md's ticket #73 section must document that the confirmation "
        "stays mandatory on poor-fit or non-empty deferred"
    )
    assert re.search(r"never skipped|never skip", section, re.IGNORECASE), (
        "AGENTS.md's ticket #73 section must state the mandatory cases are "
        "never skipped"
    )
