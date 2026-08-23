"""
Regression tests for ticket #88 (part 2 and 3): process-ticket posts short
status comments to the ticket after Phase 3 and Phase 4, and Phase 3 no
longer accepts a silently incomplete change_report as a completed phase.

Root cause (live incident): a live `orchestrate-tickets` run went silent
repeatedly, discovered only by manual follow-up. Two contributing causes
lived inside `process-ticket` itself, independent of the wave-dispatch fix
in `skills/orchestrate-tickets/SKILL.md`:

1. Only Phase 2 posted a ticket comment (the short-form plan). If the
   orchestrator session died between Phase 2 and the Final step, nobody
   looking at the ticket could tell whether Phase 3 (tests) or Phase 4
   (review) had even started, let alone how far they got.
2. A developer sub-agent was observed ending its turn having never started
   the mandated test run, with a change_report carrying neither a PASS/FAIL
   result nor an explicit blocked/in-progress status -- silently incomplete,
   not merely slow. Phase 3 had no documented handling for this shape at
   all: it wasn't a valid PASS/FAIL completion and it wasn't a legitimate
   blocked/in-progress hand-off either.

Fix:
- Phase 3 posts a short PASS/FAIL status comment after the developer
  reports, and Phase 4 posts a short APPROVE/CHANGES_REQUESTED status
  comment after the reviewer reports (mirroring the existing Phase 2 plan
  comment) -- both via `add_comment`.
- Phase 3 documents an "Incomplete report" branch: a change_report with
  neither a PASS/FAIL result nor an explicit blocked/in-progress status
  triggers exactly ONE fresh, synchronous, unnamed re-dispatch; if the retry
  is incomplete in the same way, process-ticket STOPs and reports the
  blocker -- no silent second retry, no silent proceed to Phase 4.

Red -> green: these tests fail against the pre-#88 SKILL.md (Phase 3/4 have
no comment-posting step, and Phase 3 has no incomplete-report branch at all)
and pass once both are documented.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESS_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _phase3_section(body: str) -> str:
    m = re.search(r"### Phase 3.*?(?=\n### Phase 4)", body, re.DOTALL)
    assert m, "Could not find '### Phase 3' section"
    return m.group(0)


def _phase4_section(body: str) -> str:
    m = re.search(r"### Phase 4.*?(?=\n## Final step)", body, re.DOTALL)
    assert m, "Could not find '### Phase 4' section"
    return m.group(0)


# ---------------------------------------------------------------------------
# BR3 — Phase 3 and Phase 4 each post a short status comment
# ---------------------------------------------------------------------------


def test_phase3_posts_status_comment_after_test_result():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    assert re.search(r"add_comment\(", phase3), (
        "Phase 3 must post a status comment via `add_comment(...)` after "
        "the developer reports its test result"
    )
    assert re.search(r"PASS.{0,20}FAIL|PASS/FAIL|status comment", phase3, re.IGNORECASE), (
        "Phase 3's comment step must reference the PASS/FAIL test result"
    )


def test_phase4_posts_status_comment_after_review_verdict():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4_section(body)
    assert re.search(r"add_comment\(", phase4), (
        "Phase 4 must post a status comment via `add_comment(...)` after "
        "the reviewer reports its verdict"
    )
    assert re.search(
        r"APPROVE.{0,40}CHANGES_REQUESTED|APPROVE/CHANGES_REQUESTED|review verdict",
        phase4, re.IGNORECASE,
    ), (
        "Phase 4's comment step must reference the review verdict"
    )


def test_phase3_and_phase4_comments_mirror_phase2_plan_comment():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    phase4 = _phase4_section(body)
    for phase_name, section in (("Phase 3", phase3), ("Phase 4", phase4)):
        assert re.search(r"mirrors?\s+Phase\s+2|mirror(s|ing)?\s+the\s+existing\s+Phase\s+2",
                          section, re.IGNORECASE), (
            f"{phase_name}'s new comment step should note it mirrors the "
            "existing Phase 2 plan comment"
        )


def test_mandatory_safety_gates_mention_phase3_phase4_comments():
    body = _extract_body(_read(PROCESS_MD))
    gates_m = re.search(
        r"### Mandatory safety gates.*?(?=\n## Preconditions)", body, re.DOTALL
    )
    assert gates_m, "Could not find '### Mandatory safety gates' section"
    gates = gates_m.group(0)
    assert re.search(r"test-result\s+status", gates, re.IGNORECASE) or re.search(
        r"Phase\s+3.{0,60}status", gates, re.IGNORECASE | re.DOTALL
    ), (
        "The Traceability comments gate should mention the Phase 3 "
        "test-result status comment, not just the plan and the PR link"
    )
    assert re.search(r"review-verdict\s+status", gates, re.IGNORECASE) or re.search(
        r"Phase\s+4.{0,60}status", gates, re.IGNORECASE | re.DOTALL
    ), (
        "The Traceability comments gate should mention the Phase 4 "
        "review-verdict status comment, not just the plan and the PR link"
    )


# ---------------------------------------------------------------------------
# BR4 — Phase 3's incomplete-report branch: one retry, then STOP
# ---------------------------------------------------------------------------


def test_phase3_documents_incomplete_report_branch():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    assert re.search(r"[Ii]ncomplete\s+report", phase3), (
        "Phase 3 must document an 'incomplete report' branch for a "
        "change_report with neither a PASS/FAIL result nor an explicit "
        "blocked/in-progress status"
    )
    assert re.search(r"#88", phase3), (
        "Phase 3's incomplete-report branch must reference ticket #88"
    )


def test_phase3_incomplete_report_is_exactly_one_retry():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    incomplete_m = re.search(
        r"\*\*Incomplete report.*?(?=\n\*\*After the developer reports|\Z)",
        phase3, re.DOTALL,
    )
    assert incomplete_m, "Could not find the 'Incomplete report' paragraph in Phase 3"
    incomplete = incomplete_m.group(0)
    assert re.search(r"exactly\s+\*{0,2}one\*{0,2}", incomplete, re.IGNORECASE), (
        "the incomplete-report branch must issue exactly ONE retry, not an "
        "unbounded number"
    )
    assert re.search(
        r"fresh,?\s+synchronous,?\s+unnamed", incomplete, re.IGNORECASE
    ), (
        "the retry must be a fresh, synchronous, unnamed re-dispatch, "
        "matching the rest of this pipeline's spawn discipline"
    )
    assert re.search(r"STOP", incomplete), (
        "if the retry is ALSO incomplete, Phase 3 must STOP, not retry "
        "again silently"
    )
    assert not re.search(r"retry\s+a\s+second\s+time|second\s+retry", incomplete) or re.search(
        r"do\s+not\s+silently\s+retry\s+a\s+second\s+time|"
        r"not\s+.{0,20}retry\s+a\s+second\s+time",
        incomplete, re.IGNORECASE,
    ), (
        "any mention of a second retry in this paragraph must be a "
        "prohibition, not an instruction to actually do it"
    )


def test_phase3_incomplete_report_distinct_from_blocked_in_progress():
    """The incomplete-report branch must be scoped to the shape that is
    NEITHER a valid PASS/FAIL completion NOR a legitimate blocked/
    in-progress hand-off -- it must not swallow the existing, legitimate
    blocked/in-progress bullet."""
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    assert re.search(r"\*\*Blocked/in-progress report\.\*\*", phase3), (
        "Phase 3 must still document the pre-existing 'Blocked/in-progress "
        "report' bullet unchanged"
    )
    incomplete_m = re.search(
        r"\*\*Incomplete report.*?(?=\n\*\*After the developer reports|\Z)",
        phase3, re.DOTALL,
    )
    assert incomplete_m, "Could not find the 'Incomplete report' paragraph in Phase 3"
    incomplete = incomplete_m.group(0)
    assert re.search(
        r"neither.{0,100}nor|not.{0,40}PASS/FAIL.{0,80}not.{0,40}blocked",
        incomplete, re.IGNORECASE | re.DOTALL,
    ), (
        "the incomplete-report branch must explicitly scope itself to "
        "'neither a PASS/FAIL result nor an explicit blocked/in-progress "
        "status', distinguishing it from the legitimate blocked/in-progress "
        "hand-off"
    )


# ---------------------------------------------------------------------------
# developer.md — a change report without a PASS/FAIL or blocked/in-progress
# status is not a valid phase return
# ---------------------------------------------------------------------------


def test_developer_hard_rules_documents_incomplete_report_requirement():
    text = _read(DEVELOPER_MD)
    hard_rules_m = re.search(r"## Hard rules.*", text, re.DOTALL)
    assert hard_rules_m, "developer.md must contain a '## Hard rules' section"
    hard_rules = hard_rules_m.group(0)
    assert re.search(r"#88", hard_rules), (
        "developer.md's Hard Rules must reference ticket #88's incomplete-"
        "report fix"
    )
    assert re.search(
        r"PASS/FAIL.{0,80}blocked/in-progress|blocked/in-progress.{0,80}PASS/FAIL",
        hard_rules, re.IGNORECASE | re.DOTALL,
    ), (
        "developer.md's Hard Rules must state that a change report is not "
        "complete without either a PASS/FAIL result or an explicit "
        "blocked/in-progress status"
    )


# ---------------------------------------------------------------------------
# Reviewer fix round on ticket #88: B5's justification in agents/developer.md
# and AGENTS.md must not claim concurrent/parallel wave-member processing --
# Phase C now dispatches wave members sequentially, one at a time.
# ---------------------------------------------------------------------------
#
# Root cause (review finding): both files justified the B5 working-directory/
# Serena-project safeguard with "several developer subagents run concurrently
# across different worktrees" -- true under the pre-#88 parallel wave model,
# false now that Phase C dispatches sequentially. The safeguard itself must
# stay documented (it is still real defense-in-depth), just not justified by
# a concurrency scenario that no longer exists.
#
# Red -> green: these tests fail against the pre-fix prose (which still says
# "concurrently"/"wave-based parallel processing" in the B5 justification)
# and pass once both files are reworded with a justification that holds
# post-#88, while still documenting the safeguard itself.


def _developer_b5_step1(text: str) -> str:
    m = re.search(
        r"1\.\s+\*\*B5.*?(?=\n2\.\s+\*\*Implement the plan)", text, re.DOTALL
    )
    assert m, "developer.md must contain the B5 step 1 bullet ('1. **B5 ...')"
    return m.group(0)


def _agents_md_b5_section(text: str) -> str:
    m = re.search(
        r"\*\*B5 — developer working-directory.*?(?=\n## Every git invocation)",
        text, re.DOTALL,
    )
    assert m, "AGENTS.md must contain the B5 safeguard paragraph"
    return m.group(0)


def test_developer_b5_step1_no_longer_claims_concurrent_dispatch():
    text = _read(DEVELOPER_MD)
    b5 = _developer_b5_step1(text)
    assert not re.search(r"concurrently", b5, re.IGNORECASE), (
        "developer.md's B5 step 1 must not justify the safeguard with "
        "subagents running 'concurrently' -- ticket #88 made "
        "orchestrate-tickets' wave-member dispatch sequential, one at a time"
    )
    assert not re.search(r"wave-based\s+parallel\s+processing", b5, re.IGNORECASE), (
        "developer.md's B5 step 1 must not cite 'wave-based parallel "
        "processing' as the justification -- that model no longer exists "
        "post-#88"
    )
    # The safeguard itself must still be fully documented.
    assert re.search(r"rev-parse --show-toplevel", b5), (
        "developer.md's B5 step 1 must still document the working-directory "
        "check itself -- reword the justification, don't delete the "
        "safeguard"
    )


def test_agents_md_b5_section_no_longer_claims_concurrent_dispatch():
    text = _read(AGENTS_MD)
    b5 = _agents_md_b5_section(text)
    assert not re.search(r"concurrently", b5, re.IGNORECASE), (
        "AGENTS.md's B5 section must not justify the safeguard with "
        "'concurrently' -- ticket #88 made orchestrate-tickets' wave-member "
        "dispatch sequential, one at a time"
    )
    assert not re.search(r"wave-based\s+parallel\s+processing", b5, re.IGNORECASE), (
        "AGENTS.md's B5 section must not cite 'wave-based parallel "
        "processing' as the justification -- that model no longer exists "
        "post-#88"
    )
    # The safeguard itself must still be fully documented.
    assert re.search(r"rev-parse --show-toplevel", b5), (
        "AGENTS.md's B5 section must still document the working-directory "
        "check itself -- reword the justification, don't delete the "
        "safeguard"
    )


def test_developer_and_agents_md_b5_justifications_stay_consistent():
    """Both files must agree on the new justification: a real, still-existing
    risk (session/cwd drift), not concurrency."""
    developer_b5 = _developer_b5_step1(_read(DEVELOPER_MD))
    agents_b5 = _agents_md_b5_section(_read(AGENTS_MD))
    for label, section in (("developer.md", developer_b5), ("AGENTS.md", agents_b5)):
        assert re.search(r"drift", section, re.IGNORECASE), (
            f"{label}'s B5 justification should name session/cwd drift as "
            "the real risk the safeguard defends against, mirroring the "
            "other file's wording"
        )
