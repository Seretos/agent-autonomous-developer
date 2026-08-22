"""
Regression tests for ticket #67: `worktree_remove` teardown can permanently
fail on Windows with "directory is still locked after killing 0 blocking
process(es)" (or a raw `Permission denied` on an already-empty directory)
even after B2's process-sweep (see `test_orchestrate_cwd_independent_git.py`)
comes back with zero matches.

Root cause: the blocker is not a foreign process at all. It is the
orchestrator's **own** background-job shell whose cwd silently sits inside
the worktree being torn down (the same cwd-drift mechanism fixed for git
invocations by #66 — see `test_orchestrate_cwd_independent_git.py` and
AGENTS.md's cwd-independent-git invariant). Because the lock is held by the
orchestrator's own shell, there is no foreign PID for B2's
`Get-CimInstance Win32_Process` / `pkill -f` sweep to find or kill, so
looping that kill logic can never recover — it will keep finding zero
processes forever.

Fix (Option A, detect-and-flag only): once B2's sweep comes back empty and
the first `force=true` `worktree_remove` attempt still reports the directory
locked / Permission denied on an otherwise-empty directory, classify it as
the self-cwd-lock terminal case, record the worktree path on a run-level
`manual-cleanup-needed` list, surface that list in the Phase D end-of-run
report, and STOP — no re-looping the B2 kill logic (there is no PID to
find) and no attempt to `cd`/`Set-Location` away from the directory (cwd
control is unreliable per #66).

Red -> green: these tests fail against the pre-#67 SKILL.md/AGENTS.md (no
self-cwd-lock prose in Teardown, no `manual-cleanup-needed` list surfaced in
Phase D, no terminal case named in the "Teardown order is load-bearing" Hard
rule) and pass once the self-cwd-lock case is documented as a distinct,
detect-and-flag-only path.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"

LOCKED_SIGNATURE = "directory is still locked after killing 0 blocking process(es)"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _extract_phase_d(body: str) -> str:
    m = re.search(r"## Phase D.*?(?=\n## Teardown)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Phase D' section"
    return m.group(0)


def _extract_teardown(body: str) -> str:
    m = re.search(r"## Teardown.*?(?=\n## Hard rules)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Teardown' section"
    return m.group(0)


def _extract_hard_rules(body: str) -> str:
    m = re.search(r"## Hard rules.*", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Hard rules' section"
    return m.group(0)


def _extract_sh_fence(text: str) -> str:
    m = re.search(r"```sh\s*\n(.*?)```", text, re.DOTALL)
    assert m, "Teardown must contain a fenced ```sh``` block for the POSIX recipe"
    return m.group(1)


# ---------------------------------------------------------------------------
# Regression test
# ---------------------------------------------------------------------------


def test_teardown_documents_self_cwd_lock_distinct_from_b2():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    # (a) documents the self-cwd-lock cause, cross-referencing #66.
    assert re.search(r"own\s+background-job\s+shell", td, re.IGNORECASE), (
        "Teardown must name the orchestrator's own background-job shell as "
        "the cwd-lock cause"
    )
    assert "#66" in td, (
        "Teardown must cross-reference #66 (the cwd-drift finding this case "
        "is an instance of)"
    )

    # (b) exact detection signature: B2 sweep empty + locked/Permission
    # denied on an otherwise-empty dir.
    assert LOCKED_SIGNATURE in td, (
        f"Teardown must include the exact literal string {LOCKED_SIGNATURE!r}"
    )
    assert "Permission denied" in td
    assert re.search(r"empty\s+dir", td, re.IGNORECASE) or "otherwise-empty" in td, (
        "Teardown must condition the signature on an otherwise-empty directory"
    )
    assert re.search(r"zero\s+process(es)?|0\s+process(es)?", td, re.IGNORECASE), (
        "Teardown must state B2's sweep found zero/0 processes as part of "
        "the detection signature"
    )

    # (c) explicitly distinct from B2's foreign-process case.
    assert re.search(
        r"not\s+(a\s+)?foreign[- ]process|distinct\s+from\s+B2|not\s+B2",
        td, re.IGNORECASE,
    ), "Teardown must explicitly say this case is distinct from B2's foreign-process case"


# ---------------------------------------------------------------------------
# Behavioural-change tests
# ---------------------------------------------------------------------------


def test_self_cwd_lock_is_detect_and_flag_only():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert re.search(
        r"do\s+not\s+(re-run|loop|retry)|never\s+loop", td, re.IGNORECASE
    ), "Teardown must say not to loop/re-run the B2 kill logic for this case"
    assert re.search(
        r"do\s+not\s+(attempt\s+)?(a\s+)?`?cd`?|"
        r"do\s+not\s+(attempt\s+)?`?Set-Location`?|"
        r"no\s+cd[- ]away|never\s+cd\s+away",
        td, re.IGNORECASE,
    ), "Teardown must say not to attempt a cd/Set-Location away from the directory"
    assert re.search(
        r"manual[- ]cleanup", td, re.IGNORECASE
    ), "Teardown must route the self-cwd-lock case to manual-cleanup flagging"


def test_manual_cleanup_flagged_to_user_in_phase_d():
    body = _extract_body(_read(ORCHESTRATE_MD))
    phase_d = _extract_phase_d(body)

    assert re.search(r"manual[- ]cleanup", phase_d, re.IGNORECASE), (
        "Phase D's end-of-run report must surface the manual-cleanup-needed "
        "worktree list"
    )


def test_hard_rule_teardown_order_names_self_cwd_lock_terminal_case():
    body = _extract_body(_read(ORCHESTRATE_MD))
    hard_rules = _extract_hard_rules(body)
    m = re.search(
        r"\*\*Teardown order is load-bearing.*?(?=\n- \*\*|\Z)", hard_rules, re.DOTALL
    )
    assert m, "Hard rules must contain the 'Teardown order is load-bearing' bullet"
    rule = m.group(0)

    assert re.search(r"manual[- ]cleanup", rule, re.IGNORECASE), (
        "the Teardown-order Hard rule must name the terminal "
        "flag-for-manual-cleanup step"
    )
    assert re.search(r"don't\s+loop|do\s+not\s+loop|never\s+loop", rule, re.IGNORECASE), (
        "the Teardown-order Hard rule must say don't loop the kill logic"
    )
    assert re.search(
        r"don't\s+(try\s+to\s+)?cd|do\s+not\s+(try\s+to\s+)?cd|never\s+cd",
        rule, re.IGNORECASE,
    ), "the Teardown-order Hard rule must say don't try to cd away"


# ---------------------------------------------------------------------------
# Edge cases / must-not-weaken guards
# ---------------------------------------------------------------------------


def test_b2_foreign_process_sweep_not_weakened():
    """Updated for ticket #86: the POSIX sweep replaced the old unfiltered
    `pkill -f "<worktree-path>"` recipe with a pgrep-filtered, /proc-cwd
    refined, self/ancestor/descendant-excluded B2-match primitive (see
    test_orchestrate_probe_self_match.py). This is a deliberate update to
    this pre-existing assertion, not a weakening: it now asserts the new
    POSIX form (`pgrep -f`) instead of the retired `pkill -f` literal, while
    every other assertion here (exe-name allowlist, app-server-broker.mjs
    reference) stays intact and unweakened."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert "Get-CimInstance Win32_Process" in td
    sh_block = _extract_sh_fence(td)
    assert "pgrep -f" in sh_block, (
        "the POSIX fenced recipe (not merely explanatory prose elsewhere in "
        "Teardown) must invoke pgrep -f"
    )
    for name in ("serena.exe", "uvx.exe", "uv.exe", "python.exe", "node.exe"):
        assert name in td, f"B2 sweep must still name {name}"
    assert "app-server-broker.mjs" in td


def test_self_cwd_lock_marked_windows_specific():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    # The existing POSIX-vs-Windows distinction for the directory-lock
    # failure must survive.
    assert re.search(
        r"POSIX.*unlink.*open handle|POSIX lets `git worktree remove`",
        td, re.DOTALL,
    ), "Teardown must keep the existing POSIX-can-unlink-with-open-handle note"

    # The new self-cwd-lock prose itself must also be scoped to Windows.
    self_lock_m = re.search(
        r"self-cwd-lock.*?(?=\n\d+\.\s|\n\*\*Recovery|\Z)", td, re.DOTALL | re.IGNORECASE
    )
    assert self_lock_m, "Teardown must contain a distinctly-labeled self-cwd-lock case"
    assert re.search(r"Windows", self_lock_m.group(0), re.IGNORECASE), (
        "the self-cwd-lock case must itself be marked Windows-specific"
    )


def test_agents_md_documents_self_cwd_lock_teardown():
    agents = _read(AGENTS_MD)
    m = re.search(
        r"Teardown coupling \(cross-file\).*?(?=\n## )", agents, re.DOTALL
    )
    assert m, "AGENTS.md must contain the 'Teardown coupling (cross-file)' note"
    section = m.group(0)

    assert re.search(r"self-cwd-lock|own\s+background-job\s+shell", section, re.IGNORECASE), (
        "AGENTS.md's teardown-coupling note must mirror the self-cwd-lock "
        "invariant introduced for #67"
    )
    assert "#67" in section or "#66" in section, (
        "AGENTS.md's teardown-coupling note must cross-reference #66/#67"
    )


def test_shared_locked_signature_appears_only_as_distinct_case():
    """The 'still locked / Permission denied' signature also appears in the
    existing Recovery — phantom entry and B3 blocks; make sure the new
    self-cwd-lock case is its own distinctly-labeled step and not just a
    restatement folded into those unrelated blocks."""
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    recovery_m = re.search(r"\*\*Recovery.*?(?=\n\*\*B3)", td, re.DOTALL)
    assert recovery_m, "Teardown must still contain the 'Recovery' phantom-entry section"
    b3_m = re.search(r"\*\*B3.*", td, re.DOTALL)
    assert b3_m, "Teardown must still contain the 'B3' force-unregister section"

    assert LOCKED_SIGNATURE not in recovery_m.group(0), (
        "the exact self-cwd-lock detection signature must not bleed into the "
        "unrelated phantom-entry Recovery block"
    )
    assert LOCKED_SIGNATURE not in b3_m.group(0), (
        "the exact self-cwd-lock detection signature must not bleed into the "
        "unrelated B3 force-unregister block"
    )
