"""
Regression tests for ticket #76: orchestrate-tickets MULTI mode must not
auto-pick tickets still sitting in a board's "Backlog" column when invoked
with no explicit ticket numbers (the "none" / "all open" path).

Root cause: Phase A's MULTI "none" branch spawned the conflict-analyst over
every open ticket unconditionally, including tickets a human deliberately
parked in a "Backlog" board column — silently picking them up for automated
execution with no release-gate check.

Fix: before spawning the conflict-analyst on the "none"/"all open" path,
Phase A now calls `list_board_columns(project_id)`. No board configured, or
no column literally named "Backlog" (exact/full-token match, not substring)
-> zero behavior change, filter is skipped entirely. Otherwise, open tickets
currently sitting in the "Backlog" column are dropped from the candidate set
before the analyst runs; if that empties the set, the run states so plainly
and STOPs before spawning the analyst. Survivors are passed as an explicit
subset. This gate applies ONLY to the implicit "none"/"all open" MULTI path
-- SINGLE mode and an explicit MULTI ticket subset bypass it entirely.

Phase B surfaces the skipped tickets as their own distinct group ("N tickets
skipped -- still in Backlog"), never merged into `deferred`, and the group is
display-only: it does not force the interactive AskUserQuestion gate and does
not add a clause to the clean-run predicate. It is shown in whichever Phase B
message actually prints -- the interactive gate body when one fires for other
reasons, or the non-interactive clean-run status message otherwise.

This is read/filter-only. The write side (moving tickets out of Backlog, or
similar) is sibling ticket #77's job, not this one's.

Red->green: these tests fail against the pre-fix SKILL.md/AGENTS.md (no
board-driven filter exists anywhere in Phase A, no distinct Phase B group,
no cross-file invariant note) and pass after the fix.
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


def _phase_a(body: str) -> str:
    match = re.search(
        r"## Phase A.*?(?=\n## Phase B)", body, re.DOTALL
    )
    assert match is not None, "Could not find '## Phase A' section in SKILL.md"
    return match.group(0)


def _phase_a_multi(phase_a: str) -> str:
    """Narrow Phase A down to just the MULTI-mode branch, so ordering checks
    (e.g. "the backlog filter comes before the analyst spawn") aren't thrown
    off by the unrelated "do not spawn the analyst" sentence in the SINGLE
    mode paragraph that precedes it."""
    match = re.search(r"\*\*MULTI mode\*\*.*", phase_a, re.DOTALL)
    assert match is not None, (
        "Could not find the '**MULTI mode**' branch within Phase A"
    )
    return match.group(0)


def _backlog_gate_section(multi: str) -> str:
    """Narrow the MULTI branch down to just the 'Backlog release gate' bullet
    block/subsection, the same way _phase_a_multi narrows Phase A down to the
    MULTI branch. Scoping provider-name-absence checks (and other gate-only
    assertions) to this subsection -- rather than all of Phase A -- means an
    unrelated future Phase A edit that legitimately mentions a provider name
    for other reasons can't false-fail these tests."""
    match = re.search(
        r"\*\*Backlog release gate.*?(?=\nThen spawn the analyst)",
        multi,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not find the 'Backlog release gate' bullet block within "
        "Phase A's MULTI mode branch"
    )
    return match.group(0)


def _no_board_bullet(multi: str) -> str:
    """Narrow down to just the 'No board configured' bullet, so the
    narrowed-catch-scope assertions aren't diluted by the sibling 'Board
    present but no column literally named Backlog' bullet or the rest of the
    gate prose."""
    match = re.search(
        r"- \*\*No board configured\*\*.*?(?=\n- \*\*Board present)",
        multi,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not find the 'No board configured' bullet in Phase A's "
        "MULTI mode branch"
    )
    return match.group(0)


def _phase_b(body: str) -> str:
    match = re.search(
        r"## Phase B.*?(?=\n## Phase C)", body, re.DOTALL
    )
    assert match is not None, "Could not find '## Phase B' section in SKILL.md"
    return match.group(0)


def _hard_rules(body: str) -> str:
    match = re.search(r"## Hard rules.*", body, re.DOTALL)
    assert match is not None, "Could not find '## Hard rules' section in SKILL.md"
    return match.group(0)


def _agents_backlog_section(text: str) -> str:
    match = re.search(
        r"## .*[Bb]acklog.*[Rr]elease [Gg]ate.*\(ticket #76\).*?(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not find a ticket #76 backlog release-gate section in "
        "AGENTS.md"
    )
    return match.group(0)


# ---------------------------------------------------------------------------
# Phase A: filter runs before the conflict-analyst spawn, on the "none" path
# ---------------------------------------------------------------------------


def test_backlog_gate_filters_before_analyst():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)

    assert re.search(r"list_board_columns", multi), (
        "Phase A must document calling list_board_columns to detect a "
        "Backlog column"
    )
    assert re.search(r"\bBacklog\b", multi), (
        "Phase A must name the literal 'Backlog' column"
    )

    # Ordering: the filter/gate prose must appear before the conflict-analyst
    # spawn instruction in Phase A's MULTI "none" branch text.
    analyst_spawn_match = re.search(
        r"spawn the analyst", multi, re.IGNORECASE
    )
    assert analyst_spawn_match is not None, (
        "Could not find the conflict-analyst spawn instruction in Phase A's "
        "MULTI mode branch"
    )
    board_filter_match = re.search(r"list_board_columns", multi)
    assert board_filter_match.start() < analyst_spawn_match.start(), (
        "The board-driven backlog filter must be documented BEFORE the "
        "conflict-analyst spawn instruction in Phase A's MULTI mode branch"
    )


# ---------------------------------------------------------------------------
# Round 3 fix: the "no board configured" catch is narrowly scoped -- only a
# distinguishable "board not configured" signal degrades to skip-the-filter;
# every other error class (auth, network, rate limit, permission, ambiguous)
# must surface and STOP instead.
# ---------------------------------------------------------------------------


def test_no_board_catch_is_narrowly_scoped():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)
    bullet = _no_board_bullet(multi)

    # Non-board-configured error classes (auth, network, rate limit, ...)
    # must be documented as surfacing and STOPping Phase A, not silently
    # degrading to "skip the filter".
    assert re.search(
        r"(auth|network|rate limit).{0,400}(surface|STOP)",
        bullet,
        re.IGNORECASE | re.DOTALL,
    ), (
        "The 'No board configured' bullet must route auth/network/rate-"
        "limit-class errors to surface-and-STOP language, not silent "
        "degradation to 'no board configured'"
    )

    # The catch itself must be explicitly narrowed to ONLY the
    # distinguishable "board not configured" signal.
    assert re.search(r"[Cc]atch \*\*only\*\*|catch only", bullet), (
        "The 'No board configured' bullet must state the catch is "
        "narrowed to ONLY the 'board not configured' signal"
    )

    # No blanket phrase suggesting ALL/ANY errors are caught and degraded.
    # The bullet legitimately uses "any error" once, but only qualified as
    # "any error whose message does not ... identify a missing board" --
    # i.e. routed to surface-and-STOP, not to the skip-the-filter branch.
    # Any *unqualified* "any error" occurrence would signal a blanket catch.
    for match in re.finditer(r"any error", bullet, re.IGNORECASE):
        tail = bullet[match.end():match.end() + 10]
        assert re.match(r"\s+whose", tail, re.IGNORECASE), (
            "'any error' must only appear qualified by 'whose ...' "
            "(scoping it to the narrow board-not-configured signal), never "
            "as a blanket catch-all phrase"
        )
    assert not re.search(
        r"uncaught error can never abort", bullet, re.IGNORECASE
    ), (
        "The bullet must not claim an uncaught error can never abort the "
        "run -- non-board-configured errors must STOP it"
    )


# ---------------------------------------------------------------------------
# Round 3 fix: once the backlog gate actually fires on the "none" path,
# survivors must be passed to the analyst as an explicit subset, never
# re-described as "all open".
# ---------------------------------------------------------------------------


def test_fired_gate_survivors_passed_as_explicit_subset():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)

    spawn_para_match = re.search(r"Then spawn the analyst.*", multi, re.DOTALL)
    assert spawn_para_match is not None, (
        "Could not find the 'Then spawn the analyst' paragraph in Phase A's "
        "MULTI mode branch"
    )
    spawn_para = spawn_para_match.group(0)

    # Isolate just the "once the gate actually fires" clause -- the "none"
    # path's post-filter candidate set -- not the sibling "several" bypass
    # clause or the gate-skipped "all open" case earlier in the paragraph.
    fired_clause_match = re.search(
        r"once the gate actually fires.{0,300}?filtered",
        spawn_para,
        re.IGNORECASE | re.DOTALL,
    )
    assert fired_clause_match is not None, (
        "Could not find the 'once the gate actually fires' clause "
        "describing the post-filter candidate set"
    )
    fired_clause = fired_clause_match.group(0)

    assert re.search(
        r"survivors.{0,40}explicit subset",
        fired_clause,
        re.IGNORECASE | re.DOTALL,
    ), (
        "The fired-gate clause must state survivors are passed as 'the "
        "explicit subset', with the two terms adjacent -- not merely "
        "somewhere in the same paragraph"
    )
    assert re.search(
        r"never.{0,40}re-described as .all open.|never.{0,40}all open",
        fired_clause,
        re.IGNORECASE,
    ), (
        "The fired-gate clause must state survivors are never "
        "re-described as 'all open' once filtered"
    )


# ---------------------------------------------------------------------------
# Scope: gate applies only to the implicit "none"/"all open" MULTI path
# ---------------------------------------------------------------------------


def test_explicit_subset_bypasses_gate():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)

    assert re.search(
        r"(none|all open).{0,300}(only|exclusively)|"
        r"(only|exclusively).{0,300}(none|all open)",
        phase_a,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase A must state the backlog gate applies ONLY to the "
        "'none'/'all open' MULTI path"
    )
    assert re.search(
        r"SINGLE.{0,200}bypass|bypass.{0,200}SINGLE",
        phase_a,
        re.DOTALL | re.IGNORECASE,
    ), "Phase A must state SINGLE mode bypasses the backlog gate"
    assert re.search(
        r"several.{0,200}bypass|bypass.{0,200}several|"
        r"explicit subset.{0,200}bypass|bypass.{0,200}explicit subset",
        phase_a,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase A must state an explicit MULTI ticket subset ('several') "
        "bypasses the backlog gate"
    )


# ---------------------------------------------------------------------------
# Backward compatibility: both escape hatches documented
# ---------------------------------------------------------------------------


def test_backward_compat_no_board_or_no_backlog_column():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)

    assert re.search(
        r"no board.{0,200}(zero|no) (behavior|behaviour) change|"
        r"(zero|no) (behavior|behaviour) change.{0,200}no board",
        phase_a,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase A must document that no board configured means zero "
        "behavior change (filter skipped)"
    )
    assert re.search(
        r"no column.{0,200}literally named.{0,80}Backlog|"
        r"literally named.{0,80}Backlog",
        phase_a,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase A must document the escape hatch for a board with no "
        "column literally named 'Backlog'"
    )
    assert re.search(
        r"exact.{0,40}(match|token)|full[- ]token", phase_a, re.IGNORECASE
    ), (
        "Phase A must note the Backlog column match is exact/full-token, "
        "not substring"
    )
    assert re.search(r"not substring|not a substring", phase_a, re.IGNORECASE), (
        "Phase A must explicitly rule out substring matching for the "
        "Backlog column name"
    )


# ---------------------------------------------------------------------------
# Provider-agnostic: no hardcoded github/azure column semantics
# ---------------------------------------------------------------------------


def test_gate_is_provider_agnostic():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)
    # Narrowed (round 3 fix) to just the "Backlog release gate" bullet
    # block/subsection -- the same way _phase_a_multi narrows Phase A down
    # to the MULTI branch -- so an unrelated future Phase A edit that
    # legitimately mentions a provider name for other reasons (e.g. a new
    # cross-reference elsewhere in Phase A) can't false-fail this test.
    gate_section = _backlog_gate_section(multi)

    assert re.search(
        r"provider[- ]agnostic|provider agnostic", gate_section, re.IGNORECASE
    ), "The backlog gate section must state the gate is provider-agnostic"
    assert re.search(r"list_board_columns", gate_section), (
        "The backlog gate section must ground the provider-agnostic claim "
        "in list_board_columns"
    )
    assert not re.search(
        r"github-projects-v2|azure-boards", gate_section, re.IGNORECASE
    ), (
        "The backlog gate section must NOT hardcode github-projects-v2 or "
        "azure-boards column semantics -- it must rely solely on "
        "list_board_columns' normalization"
    )

    # Stronger invariant: a rewrite that reintroduces provider-specific
    # behavior under different spellings (GitHub, Azure DevOps, GitLab, ...)
    # would still pass the two literal-string checks above. Directly assert
    # no provider name appears at all inside the gate section -- the gate's
    # detection logic must rest solely on list_board_columns' return shape,
    # never on which provider is connected.
    provider_names = r"GitHub|Azure(?:\s+DevOps)?|GitLab|Jira|Bitbucket"
    provider_match = re.search(provider_names, gate_section, re.IGNORECASE)
    assert provider_match is None, (
        "The backlog gate section must not name a specific provider "
        f"anywhere (found {provider_match.group(0)!r} if this assertion is "
        "disabled) -- detection must rely solely on list_board_columns, "
        "never on provider-conditional branching"
    )

    # Even if a bare provider name were ever legitimately needed (e.g. in a
    # cross-reference), it must never appear paired with a conditional
    # keyword -- that shape ("if...GitHub", "when...Azure") is exactly the
    # provider-conditional branching this gate must not have.
    conditional_keywords = r"if|when|unless|in case of|depending on"
    assert not re.search(
        rf"\b(?:{conditional_keywords})\b[^.\n]{{0,80}}\b(?:{provider_names})\b",
        gate_section,
        re.IGNORECASE,
    ), (
        "The backlog gate section must not gate any behavior on a specific "
        "provider name (e.g. 'if...GitHub', 'when...Azure') -- the gate is "
        "provider-agnostic by construction, not by convention"
    )
    assert not re.search(
        rf"\b(?:{provider_names})\b[^.\n]{{0,80}}\b(?:{conditional_keywords})\b",
        gate_section,
        re.IGNORECASE,
    ), (
        "The backlog gate section must not gate any behavior on a specific "
        "provider name (e.g. 'GitHub...if', 'Azure...when') -- the gate is "
        "provider-agnostic by construction, not by convention"
    )


# ---------------------------------------------------------------------------
# Phase B: distinct group, never merged into deferred
# ---------------------------------------------------------------------------


def test_backlog_skip_is_distinct_phase_b_group():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)

    assert re.search(
        r"skipped.{0,60}still in Backlog|still in Backlog", phase_b,
        re.IGNORECASE,
    ), (
        "Phase B must document the 'N tickets skipped -- still in "
        "Backlog' group"
    )
    assert re.search(
        r"never merged into.{0,40}deferred|"
        r"separate from.{0,60}deferred|"
        r"distinct from.{0,60}deferred",
        phase_b,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B must state the backlog-skip group is separate/distinct "
        "from `deferred` and never merged into it"
    )


# ---------------------------------------------------------------------------
# Phase B: display-only, does not gate the clean-run predicate
# ---------------------------------------------------------------------------


def test_backlog_skip_does_not_gate_clean_run():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)

    assert re.search(
        r"display-only|display only", phase_b, re.IGNORECASE
    ), "Phase B must state the backlog-skip group is display-only"
    assert re.search(
        r"does not force the interactive.{0,60}gate|"
        r"does not force.{0,60}AskUserQuestion",
        phase_b,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Phase B must state the backlog-skip group does not force the "
        "interactive AskUserQuestion gate"
    )

    # The clean-run predicate definition itself must carry no backlog clause.
    predicate_match = re.search(
        r"Define a \*\*clean run\*\*:.*?\.", phase_b, re.DOTALL
    )
    assert predicate_match is not None, (
        "Could not find the clean-run predicate definition in Phase B"
    )
    predicate_text = predicate_match.group(0)
    assert not re.search(r"backlog", predicate_text, re.IGNORECASE), (
        "The clean-run predicate text itself must carry no backlog-related "
        "clause -- the gate stays surface-only"
    )


# ---------------------------------------------------------------------------
# Phase B: shown in both the interactive gate body and the status message
# ---------------------------------------------------------------------------


def test_backlog_skip_shown_in_both_print_paths():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)

    # Pin the required group's exact text/shape -- "skipped" and "still in
    # Backlog" must appear together, close enough to be the same phrase, not
    # just the bare word "backlog" showing up anywhere (e.g. incidentally in
    # unrelated prose, or describing the group folded into `deferred`).
    group_phrase = r"skipped.{0,40}still in Backlog"

    item1_match = re.search(r"1\.\s+\*\*Clean run.*?(?=\n2\.\s+\*\*Otherwise)", phase_b, re.DOTALL)
    assert item1_match is not None, "Could not find Phase B item 1 (clean-run skip path)"
    item1 = item1_match.group(0)
    assert re.search(group_phrase, item1, re.IGNORECASE), (
        "Phase B item 1 (the non-interactive clean-run status message path) "
        "must surface the distinct 'N tickets skipped -- still in Backlog' "
        "group by name, not just mention the bare word 'backlog'"
    )
    assert not re.search(
        r"deferred[^.\n]{0,60}skipped.{0,40}still in Backlog|"
        r"skipped.{0,40}still in Backlog[^.\n]{0,60}(?:merged into|part of|folded into) `?deferred`?",
        item1,
        re.IGNORECASE,
    ), (
        "Phase B item 1 must not describe the backlog-skip group as merged "
        "into or part of `deferred`"
    )

    item2_match = re.search(r"2\.\s+\*\*Otherwise.*", phase_b, re.DOTALL)
    assert item2_match is not None, "Could not find Phase B item 2 (mandatory gate path)"
    item2 = item2_match.group(0)
    assert re.search(group_phrase, item2, re.IGNORECASE), (
        "Phase B item 2 (the interactive AskUserQuestion gate body) must "
        "surface the distinct 'N tickets skipped -- still in Backlog' "
        "group by name, not just mention the bare word 'backlog'"
    )
    assert not re.search(
        r"deferred[^.\n]{0,60}skipped.{0,40}still in Backlog|"
        r"skipped.{0,40}still in Backlog[^.\n]{0,60}(?:merged into|part of|folded into) `?deferred`?",
        item2,
        re.IGNORECASE,
    ), (
        "Phase B item 2 must not describe the backlog-skip group as merged "
        "into or part of `deferred`"
    )


# ---------------------------------------------------------------------------
# Zero-survivors guard: stated, and ordered before the analyst spawn
# ---------------------------------------------------------------------------


def test_zero_survivors_stops_before_analyst():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)

    zero_match = re.search(
        r"zero.surviv|empt(?:y|ies) the (candidate )?set", multi, re.IGNORECASE
    )
    assert zero_match is not None, (
        "Phase A must document a zero-survivors guard for the backlog filter"
    )
    assert re.search(r"STOP", multi), (
        "Phase A's zero-survivors guard must STOP the run"
    )

    analyst_spawn_match = re.search(r"spawn the analyst", multi, re.IGNORECASE)
    assert analyst_spawn_match is not None
    assert zero_match.start() < analyst_spawn_match.start(), (
        "The zero-survivors guard must be documented BEFORE the "
        "conflict-analyst spawn instruction"
    )


# ---------------------------------------------------------------------------
# Hard rules: one-line restatement
# ---------------------------------------------------------------------------


def test_hard_rules_restate_backlog_gate():
    body = _extract_body(_read(ORCHESTRATE_MD))
    hard_rules = _hard_rules(body)

    assert re.search(r"[Bb]acklog", hard_rules), (
        "Hard rules must restate the backlog release gate"
    )
    assert re.search(r"list_board_columns", hard_rules), (
        "Hard rules must reference list_board_columns"
    )
    assert re.search(
        r"none.{0,60}all open|all open.{0,60}none", hard_rules,
        re.DOTALL | re.IGNORECASE,
    ), (
        "Hard rules must restate the gate's scope: implicit 'none'/'all "
        "open' MULTI path only"
    )
    assert re.search(r"surface|display-only|display only", hard_rules, re.IGNORECASE), (
        "Hard rules must restate the gate is surface-only"
    )


# ---------------------------------------------------------------------------
# AGENTS.md: new cross-file section
# ---------------------------------------------------------------------------


def test_agents_md_documents_backlog_gate():
    text = _read(AGENTS_MD)
    section = _agents_backlog_section(text)

    assert re.search(r"list_board_columns", section), (
        "AGENTS.md's ticket #76 section must name list_board_columns as "
        "the detection mechanism"
    )
    assert re.search(
        r"before.{0,80}conflict-analyst|conflict-analyst.{0,80}before",
        section,
        re.DOTALL | re.IGNORECASE,
    ), (
        "AGENTS.md's ticket #76 section must document the "
        "filter-before-analyst ordering"
    )
    assert re.search(r"Phase B", section), (
        "AGENTS.md's ticket #76 section must reference Phase B"
    )
    assert re.search(
        r"surface[- ]only|display-only|display only", section, re.IGNORECASE
    ), (
        "AGENTS.md's ticket #76 section must document the surface-only "
        "Phase B behavior"
    )
    assert re.search(r"#77", section), (
        "AGENTS.md's ticket #76 section must name the #77 read-only "
        "boundary"
    )
    assert re.search(
        r"read-only|read only", section, re.IGNORECASE
    ), (
        "AGENTS.md's ticket #76 section must state this gate is "
        "read/filter-only, deferring writes to #77"
    )
    assert re.search(
        r"untriaged|never triaged|no board Status|never added to the board",
        section,
        re.IGNORECASE,
    ), (
        "AGENTS.md's ticket #76 section must document dropping untriaged "
        "tickets (no board Status at all, ticket #79), not only tickets "
        "explicitly parked in a 'Backlog' column"
    )


# ---------------------------------------------------------------------------
# Ticket #79: untriaged tickets (no board Status at all) are also dropped
# ---------------------------------------------------------------------------


def test_backlog_gate_drops_untriaged_tickets():
    """The gate must also drop open tickets that were never triaged onto the
    board at all (no board Status/column value set -- e.g. filed via
    create_ticket and never added to the board), not only tickets explicitly
    parked in a column literally named 'Backlog'."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)
    gate_section = _backlog_gate_section(multi)

    untriaged_synonym = (
        r"untriaged|never triaged|no board Status|never added to the board|"
        r"no Status/column value|no board Status/column value"
    )
    drop_verb = r"drop|filter|exclude"

    assert re.search(
        rf"(?:{untriaged_synonym}).{{0,200}}(?:{drop_verb})|"
        rf"(?:{drop_verb}).{{0,200}}(?:{untriaged_synonym})",
        gate_section,
        re.IGNORECASE | re.DOTALL,
    ), (
        "The backlog release gate section must document dropping/filtering "
        "untriaged tickets (no board Status at all), not only tickets "
        "explicitly parked in a 'Backlog' column"
    )

    # The existing full-token Backlog-column drop wording must still stand.
    assert re.search(
        r"literally named.{0,80}Backlog", gate_section, re.IGNORECASE
    ), (
        "The full-token 'literally named Backlog' wording must still be "
        "present alongside the new untriaged-drop prose"
    )


def test_untriaged_dropped_even_without_backlog_column():
    """Q2 Option A: the untriaged drop fires whenever a board is configured,
    independent of whether a literal 'Backlog' column exists."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_a = _phase_a(body)
    multi = _phase_a_multi(phase_a)
    gate_section = _backlog_gate_section(multi)

    bullet_match = re.search(
        r"no column literally named.{0,80}Backlog.*?(?=\n- \*\*Otherwise)",
        gate_section,
        re.IGNORECASE | re.DOTALL,
    )
    assert bullet_match is not None, (
        "Could not find the 'no column literally named Backlog' bullet in "
        "the backlog release gate section"
    )
    bullet = bullet_match.group(0)

    assert not re.search(
        r"skip the filter entirely", bullet, re.IGNORECASE
    ), (
        "The 'no Backlog column' bullet must no longer say the filter is "
        "skipped entirely -- the untriaged drop still applies"
    )
    assert re.search(
        r"board.{0,40}(is )?configured|board.{0,20}present",
        bullet,
        re.IGNORECASE,
    ), (
        "The 'no Backlog column' bullet must tie the untriaged drop to a "
        "board being configured, independent of the literal Backlog column"
    )
    assert re.search(
        r"untriaged|never triaged|no board Status|never added to the board",
        bullet,
        re.IGNORECASE,
    ), (
        "The 'no Backlog column' bullet must still drop untriaged tickets "
        "even though the Backlog-column drop does not apply"
    )


def test_backlog_skip_group_covers_untriaged():
    """Q1 Option 1: Phase B's display-only skipped group must be generalized
    to also cover untriaged tickets, while keeping the literal 'skipped ...
    still in Backlog' phrase pinned by other tests."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_b = _phase_b(body)

    assert re.search(
        r"skipped.{0,40}still in Backlog", phase_b, re.IGNORECASE
    ), (
        "Phase B must still surface the literal 'skipped ... still in "
        "Backlog' phrase"
    )
    assert re.search(
        r"untriaged|never triaged|no board Status|never added to the board",
        phase_b,
        re.IGNORECASE,
    ), (
        "Phase B must generalize the backlog-skip group to also cover "
        "tickets that were never triaged onto the board (no board Status)"
    )
