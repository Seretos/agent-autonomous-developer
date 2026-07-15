"""
Regression tests for ticket #77: process-ticket must move the ticket's board
card as it executes -- the write side of sibling ticket #76's read/filter-only
"Backlog release gate".

Gated on the same board-detection mechanism #76 introduced:
`list_board_columns(project_id)`, exact/full-token column-name match. No
board configured, or no column literally matching the target phase's name,
means the specific write is skipped silently -- same backward-compat
semantics as #76.

Phase -> column mapping:
- Phase 1 (context-extractor + planner begin) -> move the card to `Doing`.
- Phase 4 (reviewer invoked) -> move the card to `Review`.
- Phase 4 `CHANGES_REQUESTED` fix-loop re-dispatch -> move the card back to
  `Doing` (then to `Review` again once the re-review runs).

Per the user's decision, `Review` is the terminal automated state -- there is
NO automated `Done` write anywhere, in either process-ticket's Final step or
orchestrate-tickets' Phase D. This supersedes the ticket body's literal
"Done" wording.

Writes are best-effort and never blocking: unlike #76's read-side gate (which
STOPs on an ambiguous `list_board_columns` error), ANY failure on the write
side -- detection error, missing target column, or a failed `update_ticket`
call -- degrades to a logged warning and the pipeline continues.

Red->green: these tests fail against the pre-fix SKILL.md/AGENTS.md (no
board-write prose anywhere) and pass after the fix.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESS_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _board_section(body: str) -> str:
    match = re.search(
        r"### Board card movement.*?(?=\n### Phase 1)", body, re.DOTALL
    )
    assert match is not None, (
        "Could not find the '### Board card movement' subsection in "
        "process-ticket/SKILL.md"
    )
    return match.group(0)


def _phase1(body: str) -> str:
    match = re.search(
        r"### Phase 1.*?(?=\n### Phase 2)", body, re.DOTALL
    )
    assert match is not None, "Could not find '### Phase 1' section"
    return match.group(0)


def _phase4(body: str) -> str:
    match = re.search(
        r"### Phase 4.*?(?=\n## Final step)", body, re.DOTALL
    )
    assert match is not None, "Could not find '### Phase 4' section"
    return match.group(0)


def _final_step(body: str) -> str:
    match = re.search(
        r"## Final step.*?(?=\n## Hard rules)", body, re.DOTALL
    )
    assert match is not None, "Could not find '## Final step' section"
    return match.group(0)


def _process_hard_rules(body: str) -> str:
    match = re.search(r"## Hard rules.*", body, re.DOTALL)
    assert match is not None, "Could not find '## Hard rules' section"
    return match.group(0)


def _your_tools_bullet(hard_rules: str) -> str:
    match = re.search(r"Your tools:.*?(?=\n- \*\*|\Z)", hard_rules, re.DOTALL)
    assert match is not None, (
        "Could not find the 'Your tools:' bullet in process-ticket's Hard "
        "rules section"
    )
    return match.group(0)


# Forbidden phrasings that describe actually moving/setting/transitioning a
# board card to a Done column -- broadened beyond the original
# move[sd]?...to...Done pattern per the codex review (blocking finding 1) so
# equivalent wordings like `update_ticket(... "Done")`, "set Status to Done",
# or "transition the card to Done" are caught too. A mention is allowed only
# in two specific cases, checked separately below (round-3 codex review,
# blocking finding 2 -- the original bare `human|merge|supersede` keyword
# search was too permissive, e.g. it let "After a PR merge, process-ticket
# automatically updates the Status field to Done." slip through because
# "merge" was merely nearby):
#
# (1) Attribution -- the mention sits inside the specific "only a human (or
#     the real PR-merge event) later transitions the card to `Done`" framing
#     actually shipped in SKILL.md (in either order, human-first or
#     merge-event-first), or the standalone word "supersedes" (a much more
#     specific/uncommon word than bare "merge", used to flag a design
#     decision that supersedes older wording).
# (2) Negation -- the mention is directly negated, e.g. "... never moves the
#     card to `Done` ..." (the Final step's "no terminal write" sentence).
#     The negation word must sit immediately before the matched verb (only
#     whitespace between), not merely appear somewhere in a wide window --
#     otherwise an unrelated "never" earlier in the sentence could whitewash
#     a real forbidden write elsewhere in the same 60-char context.
_DONE_FORBIDDEN_PATTERNS = (
    r"\bmove[sd]?\b[^.\n]{0,60}\bto\b[^.\n]{0,15}`?Done`?\b",
    r"\bStatus\b.{0,20}`?Done`?\b",
    r"\btransition\w*\b.{0,40}`?Done`?\b",
    r"\bupdate_ticket\b.{0,80}`?Done`?\b",
)
_DONE_ATTRIBUTION_CONTEXT = re.compile(
    r"\ba human\b.{0,80}(?:PR-merge event|merge event)"
    r"|(?:PR-merge event|merge event).{0,80}\ba human\b"
    # `supersedes` is only accepted when it sits close to the matched `Done`
    # occurrence itself -- the context slice always ends right at that
    # match, so anchoring near the end of the slice (within 40 chars)
    # mirrors the proximity bound already used for the human/merge-event
    # alternative above, rather than letting a bare keyword match anywhere
    # in the wider 60-char lookback window.
    r"|\bsupersedes\b.{0,40}\Z",
    re.IGNORECASE | re.DOTALL,
)
_DONE_NEGATION_PREFIX = re.compile(r"\b(?:never|not|no)\s*$", re.IGNORECASE)
_DONE_NEGATION_LOOKBACK = 15


def _assert_no_forbidden_done_write(section: str, label: str) -> None:
    for pattern in _DONE_FORBIDDEN_PATTERNS:
        for match in re.finditer(pattern, section, re.IGNORECASE | re.DOTALL):
            context_start = max(0, match.start() - 60)
            context = section[context_start:match.end()]
            attributed = _DONE_ATTRIBUTION_CONTEXT.search(context)
            pre_match = section[
                max(0, match.start() - _DONE_NEGATION_LOOKBACK):match.start()
            ]
            negated = _DONE_NEGATION_PREFIX.search(pre_match)
            assert attributed or negated, (
                f"{label} must not document an automated move/set/transition "
                "to a Done column outside the permitted human/PR-merge-event "
                "attribution ('a human ... PR-merge event' or 'supersedes') "
                "or an immediately-preceding negation ('never'/'not'/'no') "
                f"(found: {match.group(0)!r})"
            )


def _fix_loop_bullet(phase4: str) -> str:
    match = re.search(
        r"- `CHANGES_REQUESTED`.*?(?=\n- `APPROVE`)", phase4, re.DOTALL
    )
    assert match is not None, (
        "Could not find the 'CHANGES_REQUESTED' fix-loop bullet in Phase 4"
    )
    return match.group(0)


def _phase_d(orchestrate_body: str) -> str:
    match = re.search(
        r"## Phase D.*?(?=\n## Teardown)", orchestrate_body, re.DOTALL
    )
    assert match is not None, "Could not find '## Phase D' section"
    return match.group(0)


def _agents_board_write_section(text: str) -> str:
    match = re.search(
        r"## [^\n]*[Bb]oard [Cc]ard [Mm]ovement[^\n]*\(ticket #77\)"
        r"[^\n]*(?:.*?)(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not find a ticket #77 board card movement section in "
        "AGENTS.md"
    )
    return match.group(0)


# ---------------------------------------------------------------------------
# Phase 1: move to Doing, gated on the board-detection mechanism
# ---------------------------------------------------------------------------


def test_phase1_writes_doing_gated_on_board():
    body = _extract_body(_read(PROCESS_MD))
    phase1 = _phase1(body)
    board_section = _board_section(body)

    assert re.search(r"list_board_columns", board_section), (
        "The Board card movement subsection must name list_board_columns "
        "as the detection mechanism"
    )
    assert re.search(r"\bDoing\b", phase1), (
        "Phase 1 must document moving the board card to 'Doing'"
    )
    assert re.search(r"[Bb]oard card movement", phase1), (
        "Phase 1 must cross-reference the Board card movement subsection"
    )


# ---------------------------------------------------------------------------
# No board / no matching column -> silent no-op (backward compat)
# ---------------------------------------------------------------------------


def test_writes_are_noop_when_no_board():
    body = _extract_body(_read(PROCESS_MD))
    board_section = _board_section(body)

    assert re.search(
        r"[Nn]o\s+board\s+configured.{0,200}skip",
        board_section,
        re.DOTALL,
    ), (
        "The Board card movement subsection must document that no board "
        "configured means the write is skipped"
    )
    assert re.search(
        r"no.{0,40}column.{0,80}(literally )?match",
        board_section,
        re.DOTALL | re.IGNORECASE,
    ), (
        "The Board card movement subsection must document that no matching "
        "column means the write is skipped"
    )
    assert re.search(r"silently", board_section, re.IGNORECASE), (
        "The Board card movement subsection must state the skip is silent"
    )


# ---------------------------------------------------------------------------
# Phase 4: move to Review
# ---------------------------------------------------------------------------


def test_phase4_writes_review():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4(body)

    assert re.search(r"\bReview\b", phase4), (
        "Phase 4 must document moving the board card to 'Review'"
    )
    assert re.search(r"[Bb]oard card movement", phase4), (
        "Phase 4 must cross-reference the Board card movement subsection"
    )


# ---------------------------------------------------------------------------
# Fix loop: back to Doing, then Review again on re-review
# ---------------------------------------------------------------------------


def test_fix_loop_writes_back_to_doing():
    body = _extract_body(_read(PROCESS_MD))
    phase4 = _phase4(body)
    fix_loop = _fix_loop_bullet(phase4)

    assert re.search(
        r"back to.{0,20}Doing|Doing.{0,20}back",
        fix_loop,
        re.IGNORECASE | re.DOTALL,
    ), (
        "The CHANGES_REQUESTED fix-loop bullet must document moving the "
        "card back to 'Doing'"
    )
    assert re.search(
        r"Review.{0,5}again|again.{0,40}Review",
        fix_loop,
        re.IGNORECASE | re.DOTALL,
    ), (
        "The CHANGES_REQUESTED fix-loop bullet must document moving the "
        "card to 'Review' again once the re-review runs"
    )


# ---------------------------------------------------------------------------
# Review is terminal -- no automated Done write anywhere
# ---------------------------------------------------------------------------


def test_no_automated_done_write_review_is_terminal():
    process_body = _extract_body(_read(PROCESS_MD))
    board_section = _board_section(process_body)
    final_step = _final_step(process_body)
    orchestrate_body = _extract_body(_read(ORCHESTRATE_MD))
    phase_d = _phase_d(orchestrate_body)

    # (a) process-ticket documents Review as terminal / last write, and the
    # Final step itself adds no terminal board write in either mode.
    assert re.search(
        r"[Rr]eview is terminal|terminal automated state",
        board_section,
    ), (
        "The Board card movement subsection must state Review is the "
        "terminal automated state"
    )
    assert re.search(
        r"last (board )?write|LAST board write",
        board_section,
        re.IGNORECASE,
    ), (
        "The Board card movement subsection must state Phase 4's Review "
        "write is the last board write process-ticket ever makes"
    )
    assert re.search(
        r"[Nn]o (completion|terminal).{0,60}board write|"
        r"no.{0,40}(completion|terminal) write",
        final_step,
        re.DOTALL,
    ), (
        "The Final step must explicitly document that it adds NO "
        "completion/terminal board write in either mode"
    )
    assert re.search(r"solo.{0,80}integration|integration.{0,80}solo", final_step, re.IGNORECASE), (
        "The Final step's no-terminal-write statement must cover both modes"
    )

    # (b) orchestrate-tickets Phase D writes no completion column.
    assert re.search(
        r"[Nn]o completion column|no `?Done`? column",
        phase_d,
    ), (
        "Phase D must document that it writes NO completion column"
    )

    # (c) none of the three sections -- including the Final step itself,
    # which is exactly where the "no completion/terminal board write" claim
    # lives (round-3 codex review, blocking finding 1) -- ever
    # moves/sets/transitions a card to a Done column, checked against
    # several equivalent phrasings (not just "move ... to Done"), with an
    # exception for the already-permitted attribution/negation framings.
    for section, label in (
        (board_section, "Board card movement subsection"),
        (phase_d, "Phase D"),
        (final_step, "Final step"),
    ):
        _assert_no_forbidden_done_write(section, label)


# ---------------------------------------------------------------------------
# Best-effort, never blocking -- looser than #76's read-side STOP behavior
# ---------------------------------------------------------------------------


def test_write_failure_degrades_to_warning():
    body = _extract_body(_read(PROCESS_MD))
    board_section = _board_section(body)

    assert re.search(r"[Bb]est-effort", board_section), (
        "The Board card movement subsection must state writes are "
        "best-effort"
    )
    assert re.search(
        r"never block|not.{0,20}block", board_section, re.IGNORECASE
    ), (
        "The Board card movement subsection must state a write failure "
        "never blocks the pipeline"
    )
    assert re.search(
        r"(logged )?warning", board_section, re.IGNORECASE
    ), (
        "The Board card movement subsection must state a failure degrades "
        "to a logged warning"
    )
    assert re.search(
        r"#76|read-side|read/filter-only", board_section, re.IGNORECASE
    ), (
        "The Board card movement subsection must contrast this best-effort "
        "behavior with #76's read-side STOP-on-ambiguous-error behavior"
    )


# ---------------------------------------------------------------------------
# Provider-agnostic
# ---------------------------------------------------------------------------


def test_board_writes_are_provider_agnostic():
    body = _extract_body(_read(PROCESS_MD))
    board_section = _board_section(body)

    assert re.search(
        r"provider[- ]agnostic|provider agnostic", board_section, re.IGNORECASE
    ), "The Board card movement subsection must state it is provider-agnostic"
    assert re.search(r"list_board_columns", board_section), (
        "The Board card movement subsection must ground the "
        "provider-agnostic claim in list_board_columns"
    )
    assert re.search(r"update_ticket", board_section), (
        "The Board card movement subsection must ground the "
        "provider-agnostic claim in update_ticket"
    )

    provider_names = r"GitHub|Azure(?:\s+DevOps)?|GitLab|Jira|Bitbucket"
    provider_match = re.search(provider_names, board_section, re.IGNORECASE)
    assert provider_match is None, (
        "The Board card movement subsection must not name a specific "
        f"provider anywhere (found {provider_match.group(0)!r} if this "
        "assertion is disabled)"
    )

    conditional_keywords = r"if|when|unless|in case of|depending on"
    assert not re.search(
        rf"\b(?:{conditional_keywords})\b[^.\n]{{0,80}}\b(?:{provider_names})\b",
        board_section,
        re.IGNORECASE,
    ), (
        "The Board card movement subsection must not gate any behavior on "
        "a specific provider name"
    )
    assert not re.search(
        rf"\b(?:{provider_names})\b[^.\n]{{0,80}}\b(?:{conditional_keywords})\b",
        board_section,
        re.IGNORECASE,
    ), (
        "The Board card movement subsection must not gate any behavior on "
        "a specific provider name"
    )


# ---------------------------------------------------------------------------
# Hard rules: update_ticket is an authorized tool
# ---------------------------------------------------------------------------


def test_hard_rules_allow_update_ticket():
    body = _extract_body(_read(PROCESS_MD))
    hard_rules = _process_hard_rules(body)
    your_tools = _your_tools_bullet(hard_rules)

    assert re.search(r"update_ticket", your_tools), (
        "process-ticket's Hard rules 'Your tools:' bullet must list "
        "update_ticket as an authorized tool, not just mention it "
        "somewhere else in the Hard rules section"
    )


# ---------------------------------------------------------------------------
# Writes use update_ticket as the mechanism
# ---------------------------------------------------------------------------


def test_writes_use_update_ticket():
    body = _extract_body(_read(PROCESS_MD))
    board_section = _board_section(body)

    assert re.search(r"update_ticket", board_section), (
        "The Board card movement subsection must name update_ticket as the "
        "write mechanism"
    )
    assert re.search(r"custom_fields", board_section), (
        "The Board card movement subsection must show the custom_fields "
        "Status write shape"
    )


# ---------------------------------------------------------------------------
# AGENTS.md: new cross-file section
# ---------------------------------------------------------------------------


def test_agents_md_documents_board_write_side():
    text = _read(AGENTS_MD)
    section = _agents_board_write_section(text)

    assert re.search(r"list_board_columns", section), (
        "AGENTS.md's ticket #77 section must name list_board_columns"
    )
    assert re.search(r"update_ticket", section), (
        "AGENTS.md's ticket #77 section must name update_ticket"
    )
    assert re.search(r"\bDoing\b", section), (
        "AGENTS.md's ticket #77 section must name the Doing column"
    )
    assert re.search(r"\bReview\b", section), (
        "AGENTS.md's ticket #77 section must name the Review column"
    )
    assert re.search(r"[Bb]est-effort", section), (
        "AGENTS.md's ticket #77 section must document best-effort semantics"
    )
    assert re.search(
        r"[Rr]eview is terminal|terminal automated state", section
    ), (
        "AGENTS.md's ticket #77 section must state Review is the terminal "
        "automated state"
    )


# ---------------------------------------------------------------------------
# Phase -> column mapping subsection documents all three transitions
# ---------------------------------------------------------------------------


def test_phase_column_mapping_subsection_exists():
    body = _extract_body(_read(PROCESS_MD))
    board_section = _board_section(body)

    assert re.search(r"Phase 1.{0,80}Doing", board_section, re.DOTALL), (
        "The Board card movement subsection must map Phase 1 to Doing"
    )
    assert re.search(r"Phase 4.{0,80}Review", board_section, re.DOTALL), (
        "The Board card movement subsection must map Phase 4 to Review"
    )
    assert re.search(
        r"fix.loop.{0,120}Doing|CHANGES_REQUESTED.{0,120}Doing",
        board_section,
        re.DOTALL | re.IGNORECASE,
    ), (
        "The Board card movement subsection must map the fix-loop "
        "re-dispatch back to Doing"
    )
