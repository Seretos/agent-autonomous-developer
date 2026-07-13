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
`repo_root` via `git -C <repo_root> …`, the same form already used elsewhere
in the file (Phase C step 1, the idle-fallback protocol's `-C
<worktree_path>`). `repo_root` is bootstrapped once via a single ambient
`git rev-parse --show-toplevel` call at the very top of Preconditions — the
one intentional exception, since you cannot `-C` into a root you haven't
discovered yet. The one non-git, cwd-dependent step (the integration-gate
test run) gets an explicit `Set-Location`/`cd <repo_root>` instead, since a
test runner has no `-C` equivalent.

Red -> green: these tests fail against the pre-#66 SKILL.md (plain git
commands relying on ambient cwd throughout Preconditions, Phase C, Phase D,
and Teardown) and pass once every git invocation is pinned via `-C
<repo_root>` (or, in the idle-fallback protocol only, `-C <worktree_path>`)
and the test run uses an explicit Set-Location/cd.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"


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


def test_idle_fallback_protocol_still_uses_worktree_path_unchanged():
    """The already-correct -C <worktree_path> fallback protocol commands must
    be left unchanged by the repo_root rewrite."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_c = _extract_phase_c(body)
    assert "git -C <worktree_path> log" in phase_c
    assert "git -C <worktree_path> status --porcelain" in phase_c
    assert re.search(r"git -C <worktree_path> rev-list\s+--count", phase_c), (
        "the idle-fallback's rev-list HEAD-ahead check must stay pinned to "
        "-C <worktree_path> (whitespace-tolerant: the source wraps the line "
        "between 'rev-list' and '--count')"
    )


# ---------------------------------------------------------------------------
# Negative guard: no state-mutating/query git command may appear WITHOUT
# -C <repo_root> (or -C <worktree_path> in the idle-fallback protocol).
# This is the primary red->green regression check.
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
