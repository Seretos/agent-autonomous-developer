"""
Regression tests for ticket #47: Codex correctness pass not re-run on
post-fix re-review.

The reviewer agent ran its Codex correctness pass on the FIRST review but
silently omitted it on the RE-review that follows a CHANGES_REQUESTED fix
cycle. The PR-gating second-pass verdict can therefore ship without an
independent Codex check.

Root cause: under-specified prompt wording in two files:
  - agents/reviewer.md  (Codex section heading / opening prose)
  - skills/process-ticket/SKILL.md  (Phase 4 re-review bullet)

Red→green anchors:
  - test_reviewer_codex_section_applies_on_every_invocation  (fails before edits)
  - test_process_ticket_rereview_is_full_review               (fails before edits)
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"
PROCESS_TICKET_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"


# ---------------------------------------------------------------------------
# Helpers (mirrors the approach in test_reviewer_codex_readiness.py)
# ---------------------------------------------------------------------------

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_codex_section(text: str) -> str:
    """Return the text of the 'Optional — Codex second opinion' section."""
    m = re.search(
        r"## Optional.*?Codex second opinion.*?(?=\n## |\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    assert m, (
        "agents/reviewer.md must contain an 'Optional — Codex second opinion' section"
    )
    return m.group(0)


def _extract_phase4_rereview_region(text: str) -> str:
    """Return the text around the Phase 4 're-run reviewer' instruction.

    Extracts the Phase 4 section from SKILL.md (from '### Phase 4' up to the
    next '##' heading or end of file).
    """
    m = re.search(
        r"### Phase 4.*?(?=\n## |\n### |\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    assert m, (
        "skills/process-ticket/SKILL.md must contain a '### Phase 4' section"
    )
    return m.group(0)


# ---------------------------------------------------------------------------
# Test 1 — REGRESSION (#47)
# The Codex section heading / opening prose must state it runs on every
# invocation where Codex is available — NOT only on the first review.
# ---------------------------------------------------------------------------

def test_reviewer_codex_section_applies_on_every_invocation():
    """
    REGRESSION (#47): The Codex section in agents/reviewer.md must make clear
    that the Codex correctness pass runs on EVERY reviewer invocation where
    Codex is available — including re-reviews after a fix cycle.

    The section heading and/or its opening prose must contain at least one of:
      'every invocation', 're-review', 'second pass', 'subsequent pass'
    (case-insensitive).

    Before the fix this assertion fails because the heading only says
    'only when the Codex plugin is active' with no mention of re-reviews or
    every-invocation scope.
    """
    text = _read(REVIEWER_MD)
    codex_section = _extract_codex_section(text)
    lower = codex_section.lower()

    has_every_invocation = "every invocation" in lower
    has_rereview = "re-review" in lower or "rereview" in lower
    has_second_pass = "second pass" in lower
    has_subsequent_pass = "subsequent pass" in lower

    assert (
        has_every_invocation
        or has_rereview
        or has_second_pass
        or has_subsequent_pass
    ), (
        "The Codex section in agents/reviewer.md must explicitly state that the "
        "pass runs on every invocation (including re-reviews after a fix cycle). "
        "Expected at least one of: 'every invocation', 're-review', 'second pass', "
        "'subsequent pass' (case-insensitive) in the section.\n\n"
        "Current section text:\n" + codex_section
    )


# ---------------------------------------------------------------------------
# Test 2 — REGRESSION (#47)
# The Phase 4 re-review bullet in process-ticket/SKILL.md must explicitly
# describe the re-spawned reviewer performing a FULL review, not a narrow
# check-off of prior blocking findings.
# ---------------------------------------------------------------------------

def test_process_ticket_rereview_is_full_review():
    """
    REGRESSION (#47): The Phase 4 'CHANGES_REQUESTED' → re-review bullet in
    skills/process-ticket/SKILL.md must make clear the re-spawned reviewer
    performs a FULL review (correctness, test coverage, consistency, and —
    if Codex is active — the Codex correctness pass), NOT merely a check
    that prior blocking findings are addressed.

    The Phase 4 section must contain the word 'full' near the re-run-reviewer
    instruction, OR the phrase 'full review' must appear in that section, AND
    the section must NOT narrow the re-review to only prior blocking findings.

    Before the fix this assertion fails because the re-review bullet says only
    're-run reviewer once' with no qualifier that it is a full review.
    """
    text = _read(PROCESS_TICKET_MD)
    phase4 = _extract_phase4_rereview_region(text)
    lower = phase4.lower()

    # The word 'full' must appear in Phase 4 near the reviewer re-run instruction.
    assert "full" in lower, (
        "Phase 4 of skills/process-ticket/SKILL.md must contain the word 'full' "
        "to qualify the re-review scope (e.g. 'full review'). "
        "The re-spawned reviewer must perform a full review, not merely verify "
        "that prior blocking findings are resolved.\n\n"
        "Current Phase 4 text:\n" + phase4
    )

    # Additionally, 'full review' or 'full re-review' should be present.
    has_full_review = "full review" in lower or "full re-review" in lower
    assert has_full_review, (
        "Phase 4 of skills/process-ticket/SKILL.md must contain 'full review' "
        "or 'full re-review' to make the re-review scope unambiguous.\n\n"
        "Current Phase 4 text:\n" + phase4
    )
