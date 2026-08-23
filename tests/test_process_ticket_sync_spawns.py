"""
Regression tests for ticket #70: Phase 3 (developer) and Phase 4 (reviewer)
lack the synchronous/unnamed spawn mandate Phase 2 (planner) already carries
from #58/#60, causing repeated silent idle-without-report inside a single
ticket's own pipeline.

Root cause: the *initial* Phase 3/4 spawns were already synchronous+unnamed
(fine). The gap is that Phase 3/4's one-round fix loop re-dispatches the
developer and re-runs the reviewer by resuming the *same, already-spawned*
agent via SendMessage. Resuming an agent via SendMessage is inherently
background/mailbox delivery regardless of how the original call was made --
silently reintroducing the #58/#60-class gap on every fix-cycle iteration.
Phase 2 (planner) already avoids this: its question-loop issues a brand-new
synchronous, unnamed Agent() call each iteration rather than resuming via
SendMessage.

Fix: give Phase 3 and Phase 4 the same synchronous/unnamed-spawn mandate
Phase 2 already carries -- including for every fix-loop re-dispatch, which
must be a fresh Agent() call, never a SendMessage resume.

Red -> green: these tests fail against the pre-#70 SKILL.md (Phase 3/4 spawns
undocumented as synchronous/unnamed, fix loop described as a re-spawn/re-run
with no explicit "fresh call, not SendMessage resume" language) and pass once
Phase 3/4 carry the same mandate as Phase 2, following the exact
regex-on-prose convention established in tests/test_process_ticket_modes.py.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESS_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _extract_phase_section(body: str, phase_header: str, next_header: str) -> str:
    m = re.search(
        re.escape(phase_header) + r".*?(?=" + re.escape(next_header) + r")",
        body,
        re.DOTALL,
    )
    assert m, f"Could not find section '{phase_header}' ending at '{next_header}'"
    return m.group(0)


def _phase3_section(body: str) -> str:
    return _extract_phase_section(body, "### Phase 3", "### Phase 4")


def _phase4_section(body: str) -> str:
    return _extract_phase_section(body, "### Phase 4", "## Final step")


# ---------------------------------------------------------------------------
# Group 1 -- Phase 3 (developer): initial spawn documented as synchronous +
# unnamed, mirroring Phase 2's wording.
# ---------------------------------------------------------------------------


def test_phase3_developer_spawn_is_synchronous_call():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    assert re.search(
        r'Agent\(subagent_type="developer".*?run_in_background:\s*false',
        phase3,
        re.DOTALL,
    ), (
        "Phase 3 must document the developer spawn as "
        '`Agent(subagent_type="developer", ..., run_in_background: false)`'
    )


def test_phase3_developer_spawn_is_unnamed():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    assert re.search(r"unnamed", phase3, re.IGNORECASE), (
        "Phase 3 must document the developer spawn as unnamed, mirroring "
        "Phase 2's 'synchronously and unnamed' wording"
    )


# ---------------------------------------------------------------------------
# Group 2 -- Phase 4 (reviewer): initial spawn AND fix-loop re-dispatch of
# both developer and reviewer documented as fresh synchronous unnamed calls.
# ---------------------------------------------------------------------------


def test_phase4_reviewer_spawn_is_synchronous_call():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4_section(body)
    assert re.search(
        r'Agent\(subagent_type="reviewer".*?run_in_background:\s*false',
        phase4,
        re.DOTALL,
    ), (
        "Phase 4 must document the reviewer spawn as "
        '`Agent(subagent_type="reviewer", ..., run_in_background: false)`'
    )


def test_phase4_reviewer_spawn_is_unnamed():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4_section(body)
    assert re.search(r"unnamed", phase4, re.IGNORECASE), (
        "Phase 4 must document the reviewer spawn as unnamed"
    )


def test_phase4_fix_loop_redispatch_is_fresh_call_for_developer():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4_section(body)
    assert re.search(
        r"(fresh|new|brand-new).{0,120}(re-spawn|re-run|spawn).{0,80}developer"
        r"|developer.{0,120}(fresh|new|brand-new)",
        phase4,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase 4's fix loop must document the developer re-dispatch as a "
        "fresh/new/brand-new Agent() call, not a resume of the prior spawn"
    )


def test_phase4_fix_loop_redispatch_is_fresh_call_for_reviewer():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4_section(body)
    assert re.search(
        r"(fresh|new|brand-new).{0,120}(re-run|re-review|reviewer)"
        r"|reviewer.{0,120}(fresh|new|brand-new)",
        phase4,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase 4's fix loop must document the reviewer re-review as a "
        "fresh/new/brand-new Agent() call, not a resume of the prior spawn"
    )


def test_phase4_fix_loop_never_sendmessage_resume():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4_section(body)
    assert re.search(
        r"never.{0,60}SendMessage.{0,60}resume|SendMessage.{0,60}resume.{0,120}never",
        phase4,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase 4's fix loop must explicitly say the re-dispatch is never a "
        "SendMessage resume of the prior developer/reviewer spawn"
    )


# ---------------------------------------------------------------------------
# Group 3 -- the precise mechanism/why: resuming via SendMessage is
# mailbox/background delivery regardless of how the original call was made.
# ---------------------------------------------------------------------------


def test_sendmessage_resume_mechanism_explained():
    body = _extract_body(_read(PROCESS_MD))
    assert re.search(
        r"resum(e|ing).{0,200}SendMessage.{0,200}(background|mailbox)"
        r"|SendMessage.{0,200}(background|mailbox).{0,200}regardless",
        body,
        re.DOTALL | re.IGNORECASE,
    ), (
        "SKILL.md must explain the precise mechanism: resuming an existing "
        "agent via SendMessage is inherently background/mailbox delivery "
        "regardless of how the original spawn was made"
    )


# ---------------------------------------------------------------------------
# Group 4 -- negative assertion: no leftover instruction to SendMessage-resume
# the developer/reviewer for the fix loop, scoped to Phase 3/4 only (the Hard
# Rules line legitimately lists SendMessage among the orchestrator's tools).
# ---------------------------------------------------------------------------


def test_no_sendmessage_resume_instruction_in_phase3_or_phase4():
    """Scoped negative check: no leftover instruction telling the orchestrator
    to SendMessage-resume the developer/reviewer for the fix loop. Matches
    that are themselves part of a *prohibition* (the word 'never' or 'not'
    appearing shortly before the match) are legitimate — e.g. "never a
    SendMessage resume" — and must not trip this assertion; only a positive
    instruction to do so should.
    """
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    phase4 = _phase4_section(body)
    pattern = re.compile(
        r"SendMessage.{0,120}(re-spawn|re-run|resum\w*).{0,80}(developer|reviewer)"
        r"|(re-spawn|re-run).{0,80}(developer|reviewer).{0,120}(via\s+)?SendMessage",
        re.DOTALL | re.IGNORECASE,
    )
    prohibition_words = re.compile(r"\bnever\b|\bnot\b|\bn't\b", re.IGNORECASE)
    for phase_name, section in (("Phase 3", phase3), ("Phase 4", phase4)):
        for m in pattern.finditer(section):
            preceding = section[max(0, m.start() - 60):m.start()]
            assert prohibition_words.search(preceding), (
                f"{phase_name} must not instruct SendMessage-resuming the "
                "developer/reviewer for the fix loop (found a positive "
                f"instruction: {m.group(0)!r})"
            )


# ---------------------------------------------------------------------------
# Group 5 -- cross-reference paragraph updated to mention the in-pipeline
# fix-loop recurrence alongside the orchestrator-level (Phase C) reference.
# ---------------------------------------------------------------------------
#
# Updated for ticket #88: the orchestrator-level occurrence of this bug class
# used to be compensated for by AGENTS.md's "B6" fallback (git-state +
# result-marker verification for parallel/named wave-member spawns). Ticket
# #88 eliminated the root cause instead — orchestrate-tickets now dispatches
# wave members sequentially, one fresh synchronous unnamed spawn at a time —
# so the cross-reference paragraph here must describe that fix, not the
# retired B6 fallback.


def test_cross_reference_paragraph_mentions_fix_loop_recurrence():
    body = _extract_body(_read(PROCESS_MD))
    m = re.search(
        r"This same class of bug.*?(?=\*\*After PLAN_FINAL)",
        body,
        re.DOTALL,
    )
    assert m, (
        "Could not find the 'This same class of bug...' cross-reference "
        "paragraph"
    )
    cross_ref = m.group(0)
    assert re.search(r"Phase 3|Phase 4|fix loop", cross_ref, re.IGNORECASE), (
        "The cross-reference paragraph must also mention the in-pipeline "
        "Phase 3/4 fix-loop recurrence of this bug class, alongside the "
        "orchestrator-level reference, so a future contributor doesn't "
        "reintroduce a third instance"
    )
    assert re.search(r"#88", cross_ref), (
        "The cross-reference paragraph must reference ticket #88's fix for "
        "the orchestrator-level occurrence"
    )
    assert not re.search(r"\bB6\b", cross_ref), (
        "The cross-reference paragraph must no longer reference the retired "
        "B6 fallback — ticket #88 replaced it with sequential/unnamed "
        "dispatch, described in `skills/orchestrate-tickets/SKILL.md`'s "
        "Phase C, not compensated for here"
    )


# ---------------------------------------------------------------------------
# Group 6 -- consistency with Phase 2: Phase 3 and Phase 4 use the same
# `run_in_background: false` + unnamed phrasing token that Phase 2 uses.
# ---------------------------------------------------------------------------


def test_phase2_baseline_uses_run_in_background_false_and_unnamed():
    body = _extract_body(_read(PROCESS_MD))
    phase2_m = re.search(r"### Phase 2.*?(?=### Phase 3)", body, re.DOTALL)
    assert phase2_m, "Could not find Phase 2 section"
    phase2 = phase2_m.group(0)
    assert "run_in_background: false" in phase2
    assert re.search(r"unnamed", phase2, re.IGNORECASE)


def test_phase3_and_phase4_match_phase2_token_usage():
    body = _extract_body(_read(PROCESS_MD))
    phase3 = _phase3_section(body)
    phase4 = _phase4_section(body)
    for phase_name, section in (("Phase 3", phase3), ("Phase 4", phase4)):
        assert "run_in_background: false" in section, (
            f"{phase_name} must use the literal 'run_in_background: false' "
            "token, matching Phase 2"
        )
        assert re.search(r"unnamed", section, re.IGNORECASE), (
            f"{phase_name} must use 'unnamed' language, matching Phase 2"
        )
