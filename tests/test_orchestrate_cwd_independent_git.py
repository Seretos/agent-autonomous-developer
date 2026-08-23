"""
Regression tests for ticket #66: every git invocation in
`skills/orchestrate-tickets/SKILL.md` must be cwd-independent.

Root cause: in background/job-mode invocations the shell's cwd can silently
reset between tool calls (potentially onto one of the fleet's own worker
worktrees). Every plain git command in the skill that relied on the
ambient/persisted cwd — `git checkout <integration>`, `git merge --no-ff
<branch>`, `git status --porcelain`, `git push origin <integration>`, etc. —
could therefore be silently redirected into the wrong working tree. A
misdirected `git merge` in particular can report a bogus "Already up to
date." with no error, risking a combined PR that silently omits a ticket's
changes. Reproduced in a live run; not hypothetical.

Fix: every git invocation in the skill is pinned to an explicitly-captured
`repo_root` via `git -C <repo_root> …`. `repo_root` is bootstrapped once via
a single ambient `git rev-parse --show-toplevel` call at the very top of
Preconditions — the one intentional exception, since you cannot `-C` into a
root you haven't discovered yet. The one non-git, cwd-dependent step (the
integration-gate test run) gets an explicit `Set-Location`/`cd <repo_root>`
instead, since a test runner has no `-C` equivalent.

Note (ticket #88): the former idle-fallback protocol's own `-C
<worktree_path>` commands (`git -C <worktree_path> log`/`status --porcelain`/
`rev-list --count`) were part of the B6 self-healing apparatus, which ticket
#88 removed entirely — Phase C now dispatches wave members sequentially and
reads each member's ending state directly from its own synchronous report,
so there is nothing left in Phase C that runs `-C <worktree_path>`. This
file's own #66 invariant (every OTHER git invocation pinned to `-C
<repo_root>`) is unaffected by that removal.

Red -> green: these tests fail against the pre-#66 SKILL.md (plain git
commands relying on ambient cwd throughout Preconditions, Phase C, Phase D,
and Teardown) and pass once every git invocation is pinned via `-C
<repo_root>` and the test run uses an explicit Set-Location/cd.
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


def _extract_preconditions(body: str) -> str:
    m = re.search(r"## Preconditions.*?(?=\n## Phase A)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Preconditions' section"
    return m.group(0)


def _extract_phase_c(body: str) -> str:
    m = re.search(r"## Phase C.*?(?=\n## Phase D)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Phase C' section"
    return m.group(0)


def _extract_phase_d(body: str) -> str:
    m = re.search(r"## Phase D.*?(?=\n## Teardown)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Phase D' section"
    return m.group(0)


def _extract_teardown(body: str) -> str:
    m = re.search(r"## Teardown.*", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Teardown' section"
    return m.group(0)


# ---------------------------------------------------------------------------
# Positive assertions: the -C <repo_root> form is present for every converted
# command.
# ---------------------------------------------------------------------------


def test_precondition0_guard_uses_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    pre = _extract_preconditions(body)
    assert "git -C <repo_root> rev-parse --abbrev-ref HEAD" in pre
    assert "git -C <repo_root> rev-parse --git-dir" in pre
    assert "git -C <repo_root> rev-parse --git-common-dir" in pre


def test_precondition2_fetch_pull_use_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    pre = _extract_preconditions(body)
    assert "git -C <repo_root> fetch origin" in pre
    assert "git -C <repo_root> pull --ff-only" in pre


def test_precondition3_branch_and_push_use_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    pre = _extract_preconditions(body)
    assert "git -C <repo_root> branch <integration> <base>" in pre
    assert "git -C <repo_root> push -u origin <integration>" in pre


def test_phase_c_b4_gate_uses_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_c = _extract_phase_c(body)
    assert re.search(r"git -C <repo_root> (checkout|switch) <integration>", phase_c)
    assert "git -C <repo_root> status --porcelain" in phase_c
    assert "git -C <repo_root> diff" in phase_c


def test_phase_c_merge_uses_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_c = _extract_phase_c(body)
    assert "git -C <repo_root> merge --no-ff <branch>" in phase_c


def test_phase_c_push_uses_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_c = _extract_phase_c(body)
    assert "git -C <repo_root> push origin <integration>" in phase_c


def test_phase_d_checkout_base_uses_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_d = _extract_phase_d(body)
    assert re.search(r"git -C <repo_root> (checkout|switch) <base>", phase_d)


def test_teardown_branch_delete_uses_repo_root():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    assert "git -C <repo_root> branch -d <branch>" in td


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_exactly_one_ambient_show_toplevel_with_rationale():
    body = _extract_body(_read(ORCHESTRATE_MD))
    matches = re.findall(r"git rev-parse --show-toplevel", body)
    assert len(matches) == 1, (
        "exactly one ambient 'git rev-parse --show-toplevel' bootstrap call "
        "is allowed — every other git invocation must be pinned via -C"
    )
    assert "-C <repo_root> rev-parse --show-toplevel" not in body, (
        "the bootstrap call is inherently ambient (you can't -C into a root "
        "you haven't discovered yet) — it must not itself be -C-pinned"
    )
    assert re.search(
        r"one\s+intentional\s+ambient\s+git\s+call|"
        r"sole\s+intentional\s+ambient\s+git\s+call",
        body, re.IGNORECASE,
    ), (
        "SKILL.md must document the rationale for the one ambient git call "
        "explicitly, so a future contributor doesn't 'fix' it by accident"
    )


def test_integration_gate_test_run_has_explicit_cd():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_c = _extract_phase_c(body)
    gate_m = re.search(
        r"Integration gate.*?(?=\n\s*- \*\*On GREEN)", phase_c, re.DOTALL
    )
    assert gate_m, "Phase C must contain the Integration gate step"
    gate = gate_m.group(0)
    assert re.search(r"Set-Location <repo_root>|cd <repo_root>", gate), (
        "the non-git integration-gate test run must document an explicit "
        "Set-Location/cd <repo_root> as its first statement, since a test "
        "runner has no -C equivalent"
    )


def test_teardown_recovery_branch_delete_pinned():
    """Edge case called out by the plan explicitly: the Teardown recovery
    path's 'git branch -d <branch>' must be pinned too, not just the
    happy-path git commands in Preconditions/Phase C/Phase D."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    recovery_m = re.search(r"\*\*Recovery.*?(?=\n\*\*B3)", td, re.DOTALL)
    assert recovery_m, "Teardown must contain the 'Recovery' phantom-entry section"
    assert "git -C <repo_root> branch -d <branch>" in recovery_m.group(0)


def test_prohibition_prose_on_raw_worktree_commands_left_unpinned():
    """The plan explicitly says prohibition prose ('Never git worktree add',
    'do not ... git worktree remove by hand') describes commands the skill
    must NOT run, so it stays as-is — no -C form (there is nothing to pin)."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    assert "git worktree add" in body
    assert "git worktree remove" in body


def test_idle_fallback_protocol_removed_by_ticket_88():
    """Superseded by ticket #88: the idle-fallback protocol's own
    `-C <worktree_path>` commands (`git -C <worktree_path> log`/
    `status --porcelain`/`rev-list --count`) were part of the B6 apparatus,
    which ticket #88 removed entirely — Phase C now reads each member's
    ending state directly from its own synchronous report, sequentially, so
    there is no more `-C <worktree_path>` git invocation in Phase C to keep
    pinned. This replaces
    test_idle_fallback_protocol_still_uses_worktree_path_unchanged, which
    asserted those now-removed commands stayed present."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_c = _extract_phase_c(body)
    assert "git -C <worktree_path>" not in phase_c, (
        "Phase C must no longer contain any '-C <worktree_path>' git "
        "invocation — the idle-fallback protocol that used it was removed "
        "by ticket #88"
    )


# ---------------------------------------------------------------------------
# Negative guard: no state-mutating/query git command may appear WITHOUT
# -C <repo_root>. This is the primary red->green regression check.
# ---------------------------------------------------------------------------


def test_negative_guard_no_bare_state_mutating_git_commands():
    body = _extract_body(_read(ORCHESTRATE_MD))
    # Matches "git " immediately followed by one of these subcommands, i.e.
    # with NO "-C <something>" in between. A pinned invocation like
    # "git -C <repo_root> merge" or "git -C <worktree_path> status" does NOT
    # match, because "-C ..." sits between "git" and the subcommand.
    forbidden_pattern = re.compile(
        r"git\s+(merge|push|checkout|switch|branch|status|diff|fetch|pull)\b"
    )
    offenders = [m.group(0) for m in forbidden_pattern.finditer(body)]
    assert offenders == [], (
        "found git command(s) relying on ambient/persisted cwd instead of "
        f"an explicit -C <repo_root>: {offenders}"
    )


def test_negative_guard_no_bare_rev_parse_guard_checks():
    body = _extract_body(_read(ORCHESTRATE_MD))
    assert "git rev-parse --abbrev-ref HEAD" not in body, (
        "Precondition 0's abbrev-ref guard must be pinned via -C <repo_root>"
    )
    assert "git rev-parse --git-dir" not in body, (
        "Precondition 0's --git-dir guard must be pinned via -C <repo_root>"
    )
    assert "git rev-parse --git-common-dir" not in body, (
        "Precondition 0's --git-common-dir guard must be pinned via "
        "-C <repo_root>"
    )


# ---------------------------------------------------------------------------
# Reviewer fix round on ticket #88: AGENTS.md's own description of the
# cwd-independence rule must not list the removed idle-fallback protocol's
# `-C <worktree_path>` commands as a still-standing exception.
# ---------------------------------------------------------------------------
#
# Root cause (review finding): AGENTS.md's "Every git invocation in
# orchestrate-tickets must be cwd-independent" section still said the -C
# <repo_root> form was "the same form the file already used for Phase C's
# branch-point capture and (with <worktree_path> instead) the idle-fallback
# protocol", and its Invariant paragraph still listed "the idle-fallback
# protocol's git -C <worktree_path> ... commands" as one of "the only two
# standing exceptions". Ticket #88 removed that protocol entirely, and (per
# test_idle_fallback_protocol_removed_by_ticket_88 above) there is no more
# `-C <worktree_path>` invocation anywhere in
# skills/orchestrate-tickets/SKILL.md, so this exception is now vacuous.
#
# Red -> green: these tests fail against the pre-fix AGENTS.md wording (which
# still lists the idle-fallback protocol as a live standing exception) and
# pass once that vacuous exception is dropped or clearly marked historical
# with clean surrounding grammar.


def _agents_md_cwd_section(text: str) -> str:
    m = re.search(
        r"## Every git invocation in orchestrate-tickets must be "
        r"cwd-independent.*?(?=\n## Why the project id)",
        text, re.DOTALL,
    )
    assert m, (
        "AGENTS.md must contain the '## Every git invocation in "
        "orchestrate-tickets must be cwd-independent' section"
    )
    return m.group(0)


def test_agents_md_cwd_section_does_not_claim_two_standing_exceptions():
    text = _read(AGENTS_MD)
    section = _agents_md_cwd_section(text)
    assert not re.search(r"only\s+two\s+standing\s+exceptions", section, re.IGNORECASE), (
        "AGENTS.md's cwd-independence Invariant paragraph must no longer "
        "claim there are 'only two standing exceptions' -- the "
        "idle-fallback protocol's -C <worktree_path> commands were removed "
        "by ticket #88, and there is only one exception left (the bootstrap "
        "'git rev-parse --show-toplevel' call)"
    )


def test_agents_md_cwd_section_idle_fallback_not_listed_as_live_exception():
    """The idle-fallback protocol must not be presented as a currently-live
    exception to the -C <repo_root> rule. It may still be mentioned as
    historical context (clearly marked as removed/no-longer-applicable), but
    not phrased as a standing/live carve-out."""
    text = _read(AGENTS_MD)
    section = _agents_md_cwd_section(text)
    live_exception_phrasing = re.search(
        r"exceptions?\s+are\s+the\s+single\s+bootstrap.{0,40}call,?\s+and\s+the\s+"
        r"idle-fallback\s+protocol",
        section, re.IGNORECASE | re.DOTALL,
    )
    assert live_exception_phrasing is None, (
        "AGENTS.md must not phrase the idle-fallback protocol's "
        "-C <worktree_path> commands as a currently-standing exception "
        "alongside the bootstrap call -- ticket #88 removed that protocol "
        "entirely, so it can no longer be a live exception"
    )
    if re.search(r"idle-fallback\s+protocol", section, re.IGNORECASE):
        # If still mentioned at all, it must be clearly marked historical /
        # no-longer-applicable / removed.
        assert re.search(
            r"historical|no\s+longer\s+applicable|removed|ticket\s+#88",
            section, re.IGNORECASE,
        ), (
            "if AGENTS.md's cwd-independence section still mentions the "
            "idle-fallback protocol at all, it must clearly mark it as "
            "historical/removed/no-longer-applicable, not a live exception"
        )


def test_agents_md_cwd_section_grammar_stays_clean_single_exception():
    """Positive check: the section should now clearly state there is a
    single standing exception (the bootstrap show-toplevel call), so the
    Invariant paragraph reads cleanly rather than dangling after the
    idle-fallback clause was dropped."""
    text = _read(AGENTS_MD)
    section = _agents_md_cwd_section(text)
    assert re.search(
        r"single\s+standing\s+exception|one\s+intentional\s+exception|"
        r"sole\s+(intentional\s+)?exception",
        section, re.IGNORECASE,
    ), (
        "AGENTS.md's cwd-independence Invariant paragraph must clearly state "
        "there is now a single standing exception (the bootstrap "
        "'git rev-parse --show-toplevel' call), with clean grammar -- not a "
        "dangling sentence left over from removing the idle-fallback clause"
    )


# ---------------------------------------------------------------------------
# Third fix-loop round on ticket #88: AGENTS.md's cwd-independence section
# still pointed the "-C <repo_root>" example at Phase C's branch-point
# capture step, which this same diff removed along with the rest of the B6
# apparatus (see test_idle_fallback_protocol_removed_by_ticket_88 above and
# its docstring). `grep -n "branch point\|branch_point_sha"
# skills/orchestrate-tickets/SKILL.md` returns zero hits, so the "the same
# form the file already used for Phase C's branch-point capture" clause in
# AGENTS.md now dangles, referencing something that no longer exists in the
# skill it describes.
#
# Red -> green: this test fails against the pre-fix AGENTS.md wording (which
# still names "Phase C's branch-point capture" as a still-existing example)
# and passes once that dangling clause is dropped or repointed at something
# that still exists (e.g. Precondition 0's own -C <repo_root>-pinned guard).


def test_agents_md_cwd_section_does_not_reference_removed_branch_point_capture():
    text = _read(AGENTS_MD)
    section = _agents_md_cwd_section(text)
    assert "branch-point capture" not in section, (
        "AGENTS.md's cwd-independence section must not reference Phase C's "
        "branch-point capture step as a still-existing example -- ticket #88 "
        "removed that step (and the rest of the B6 apparatus) from "
        "skills/orchestrate-tickets/SKILL.md, so the clause now dangles. "
        "Repoint the example at something that still exists (e.g. "
        "Precondition 0's own -C <repo_root>-pinned guard) or drop the clause."
    )
