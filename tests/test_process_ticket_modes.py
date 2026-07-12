"""
Regression tests for ticket #62: process-ticket `mode` parameter
(solo default vs. integration, orchestrator-invoked).

Root cause / rework: orchestrate-tickets is being reworked into a wave-based
fleet model with a shared integration branch. Per-wave members now run
process-ticket in a mode where the caller (the orchestrator) owns the push,
draft-PR, and ticket link-comment — process-ticket only commits locally.
The historical default behaviour (own push + own draft PR + own ticket
comment) must remain unchanged as the `solo` default so direct/manual
invocations are unaffected.

Red→green: these tests fail against the pre-rework SKILL.md (no `mode`
parameter, unconditional push/create_pr/add_comment, self-detecting cwd-only
branch guard) and pass after the mode-gated rework.
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


# ---------------------------------------------------------------------------
# Group 1 — mode parameter exists, solo is the default
# ---------------------------------------------------------------------------


def test_mentions_mode_parameter():
    """SKILL.md body must document a `mode` parameter."""
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert "mode" in body.lower(), (
        "skills/process-ticket/SKILL.md must document a 'mode' parameter"
    )


def test_solo_mode_is_default():
    """`solo` must be documented as the default mode."""
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert re.search(r"`solo`.{0,40}default|default.{0,40}`solo`", body, re.DOTALL), (
        "skills/process-ticket/SKILL.md must document 'solo' as the default mode"
    )


def test_integration_mode_named():
    """`integration` mode must be named as the orchestrator-invoked alternative."""
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert "integration" in body.lower(), (
        "skills/process-ticket/SKILL.md must document an 'integration' mode"
    )


# ---------------------------------------------------------------------------
# Group 2 — integration mode skips push / create_pr / ticket comment
# ---------------------------------------------------------------------------


def test_integration_mode_skips_push():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert re.search(r"integration.{0,400}skip.{0,200}push", body, re.DOTALL | re.IGNORECASE) or \
        re.search(r"push.{0,200}only.{0,40}solo", body, re.DOTALL | re.IGNORECASE), (
        "skills/process-ticket/SKILL.md must document that 'integration' mode "
        "skips the push step (caller owns it)"
    )


def test_integration_mode_skips_create_pr():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert re.search(r"integration.{0,400}skip.{0,200}create_pr", body, re.DOTALL | re.IGNORECASE) or \
        re.search(r"create_pr.{0,200}only.{0,40}solo", body, re.DOTALL | re.IGNORECASE), (
        "skills/process-ticket/SKILL.md must document that 'integration' mode "
        "skips create_pr (caller owns it)"
    )


def test_integration_mode_skips_ticket_comment():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert re.search(r"integration.{0,400}skip.{0,200}(link-comment|add_comment|ticket comment)",
                      body, re.DOTALL | re.IGNORECASE) or \
        re.search(r"(link-comment|add_comment|ticket comment).{0,200}(only|solo).{0,60}(solo|only)",
                   body, re.DOTALL | re.IGNORECASE), (
        "skills/process-ticket/SKILL.md must document that 'integration' mode "
        "skips the ticket link-comment (caller owns it)"
    )


def test_commit_step_runs_in_both_modes():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert re.search(r"commit.{0,200}both\s+modes|both\s+modes.{0,200}commit", body, re.DOTALL | re.IGNORECASE), (
        "skills/process-ticket/SKILL.md must document that the commit step "
        "runs in BOTH modes"
    )


def test_caller_owns_push_and_pr_in_integration_mode():
    """The doc must say the caller (orchestrator) owns push/PR/comment in integration mode."""
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert "caller" in body.lower(), (
        "skills/process-ticket/SKILL.md must document that the caller "
        "(orchestrator) owns push/create_pr/comment in integration mode"
    )


# ---------------------------------------------------------------------------
# Group 3 — branch+worktree guard accepts a caller-supplied worktree_path
# ---------------------------------------------------------------------------


def test_guard_mentions_worktree_path_parameter():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert "worktree_path" in body, (
        "skills/process-ticket/SKILL.md must document a caller-supplied "
        "'worktree_path' parameter used by the branch+worktree guard in "
        "integration mode"
    )


def test_guard_runs_git_dash_c_against_worktree_path():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert "git -C" in body, (
        "skills/process-ticket/SKILL.md must document running 'git -C "
        "<worktree_path>' checks against the caller-supplied path in "
        "integration mode"
    )


def test_stop_when_integration_mode_missing_worktree_path():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert re.search(r"no.{0,40}worktree_path.{0,120}stop|stop.{0,120}no.{0,40}worktree_path",
                      body, re.DOTALL | re.IGNORECASE), (
        "skills/process-ticket/SKILL.md must document STOPping when "
        "mode=integration is given without a worktree_path"
    )


# ---------------------------------------------------------------------------
# Group 4 — never-on-main invariant preserved in BOTH modes
# ---------------------------------------------------------------------------


def test_never_on_main_still_checked_in_both_modes():
    """
    REGRESSION ANCHOR: the main/master STOP check must still be present and
    must not be described as relaxed for integration mode.
    """
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert "main" in body and "STOP" in body, (
        "skills/process-ticket/SKILL.md must still document the main/master "
        "STOP check"
    )
    assert "not relaxed" in body.lower() or "not be relaxed" in body.lower() or "still stop" in body.lower(), (
        "skills/process-ticket/SKILL.md must explicitly state the never-on-main "
        "invariant is NOT relaxed for integration mode"
    )


# ---------------------------------------------------------------------------
# Group 5 — Final step 1 (commit) targets worktree_path explicitly in
# integration mode (review round 2, finding 2)
# ---------------------------------------------------------------------------


def _extract_final_step_section(body: str) -> str:
    section_m = re.search(
        r"1\. \*\*Commit\*\*.*?(?=\n2\. \*\*Push\*\*)", body, re.DOTALL
    )
    assert section_m, (
        "skills/process-ticket/SKILL.md must contain a numbered Final-step "
        "'1. **Commit**' section immediately followed by '2. **Push**'"
    )
    return section_m.group(0)


def test_commit_step_documents_dash_c_worktree_path_in_integration_mode():
    """Regression for ticket #62 review round 2, finding 2: Preconditions 2's
    branch/worktree guard was fixed to run `git -C <worktree_path> ...` in
    integration mode instead of self-detecting cwd, but the Final step's
    commit commands were left as bare `git add -A` / `git commit`, the same
    self-detecting-cwd assumption the guard fix was meant to eliminate. If the
    orchestrator's session cwd is the main checkout when it reaches this step,
    the commit would silently land in the wrong repository/branch.
    """
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    commit_section = _extract_final_step_section(body)
    assert re.search(r"git\s+-C\s+<worktree_path>\s+add\s+-A", commit_section), (
        "The commit step must document 'git -C <worktree_path> add -A' for "
        "integration mode, not a bare 'git add -A' relying on cwd"
    )
    assert re.search(r"git\s+-C\s+<worktree_path>\s+commit\s+-m", commit_section), (
        "The commit step must document 'git -C <worktree_path> commit -m ...' "
        "for the single-line message case in integration mode"
    )
    assert re.search(r"git\s+-C\s+<worktree_path>\s+commit\s+-F", commit_section), (
        "The commit step must document 'git -C <worktree_path> commit -F "
        "...' for the multi-line message case in integration mode"
    )


def test_commit_step_solo_mode_unaffected_bare_git():
    """`solo` mode must remain unaffected — it still runs bare git commands
    against the invoking session's own cwd inside the worktree, with no
    `-C <worktree_path>` needed.
    """
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    commit_section = _extract_final_step_section(body)
    assert re.search(r"`solo`\s+mode.{0,200}git add -A", commit_section, re.DOTALL), (
        "The commit step must document that 'solo' mode commits with plain "
        "'git add -A' against the invoking session's own cwd, unchanged"
    )


def test_commit_step_mirrors_precondition_guard_fix():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    commit_section = _extract_final_step_section(body)
    assert re.search(r"mirror.{0,60}(guard|precondition)|guard.{0,60}mirror",
                      commit_section, re.DOTALL | re.IGNORECASE), (
        "The commit step should note it mirrors the branch/worktree guard's "
        "own -C <worktree_path> fix in Preconditions 2, so the two don't "
        "drift back out of sync"
    )
