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
    # Round 3 (ticket #64 finding 1): the gitignore guarantee moved to its own
    # step BEFORE the commit, so the commit is now numbered step 2 (following
    # step 1's gitignore guarantee) and push is step 3 — not 1/2 as before.
    section_m = re.search(
        r"2\. \*\*Commit\*\*.*?(?=\n3\. \*\*Push\*\*)", body, re.DOTALL
    )
    assert section_m, (
        "skills/process-ticket/SKILL.md must contain a numbered Final-step "
        "'2. **Commit**' section immediately followed by '3. **Push**' "
        "(step 1 is the gitignore guarantee, which now runs before the commit)"
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


# ---------------------------------------------------------------------------
# Group 6 — ticket #64: Final step writes a result-marker file
# ---------------------------------------------------------------------------
#
# Root cause: orchestrate-tickets Phase C has no reliable way to recover a
# wave member's reviewer verdict / test result when its Final-step report
# never arrives (background/named Agent spawn, mailbox delivery can drop —
# see AGENTS.md's B6 note and skills/orchestrate-tickets/SKILL.md's Phase C
# fallback). The fix: process-ticket's Final step now writes a small
# result-marker JSON file into the worktree, unconditionally in both modes,
# right after the commit.
#
# Red -> green: these tests fail against the pre-#64 SKILL.md (no marker
# step documented at all) and pass once the Final step documents writing
# '.process-ticket-result.json' after the commit, in both modes.


def test_final_step_writes_result_marker():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    assert ".process-ticket-result.json" in body, (
        "skills/process-ticket/SKILL.md's Final step must document writing "
        "'.process-ticket-result.json'"
    )
    assert "branch" in body and "verdict" in body and "test" in body, (
        "the documented marker must include branch, verdict, and test fields"
    )


def test_result_marker_written_in_both_modes():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    marker_m = re.search(r"\d\.\s+\*\*Write a result-marker file\*\*.*", body, re.DOTALL)
    assert marker_m, "must find the marker-write step"
    marker_section = marker_m.group(0)
    assert re.search(r"both\s+modes|unconditional", marker_section, re.IGNORECASE), (
        "the result-marker step must be documented as unconditional / running "
        "in both modes, not mode-gated"
    )


def test_result_marker_written_after_commit():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    commit_idx = body.find("2. **Commit**")
    marker_idx = body.find("**Write a result-marker file**")
    assert commit_idx != -1, "Final step's commit step must exist"
    assert marker_idx != -1, "result-marker step must be documented"
    assert commit_idx < marker_idx, (
        "the result-marker step must be documented AFTER the commit step"
    )


# ---------------------------------------------------------------------------
# Group 6b — ticket #64 round 3, finding 1: the gitignore append must be
# folded into THIS run's own commit, not left uncommitted for a later,
# unrelated ticket's `git add -A` to sweep up.
# ---------------------------------------------------------------------------
#
# Root cause (round 2's bug): the gitignore check/append was documented as
# part of the marker-write step, which runs AFTER the commit. Since that
# gitignore change is never committed by the run that made it, it sat as an
# uncommitted tracked-file change — the NEXT ticket processed in that same
# worktree/repo would silently sweep it into its own commit via `git add -A`,
# misattributed.
#
# Fix: the gitignore check/append is now its own Final step 1, run BEFORE
# step 2's commit, so any append becomes part of the current ticket's own
# commit.
#
# Red -> green: these tests fail against the round-2 SKILL.md (gitignore
# check documented only inside the post-commit marker-write step, with no
# standalone pre-commit step and no "before the commit" ordering language)
# and pass once Final step 1 is the gitignore guarantee, ahead of the commit.


def test_gitignore_guarantee_is_final_step_1_before_commit():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    final_m = re.search(r"## Final step.*", body, re.DOTALL)
    assert final_m, "SKILL.md must contain a '## Final step' section"
    final_step = final_m.group(0)
    gitignore_idx = final_step.find("1. **Target-repo `.gitignore` guarantee**")
    commit_idx = final_step.find("2. **Commit**")
    assert gitignore_idx != -1, (
        "Final step must have a standalone numbered step 1 for the "
        "target-repo .gitignore guarantee"
    )
    assert commit_idx != -1, "Final step must have a numbered step 2 commit"
    assert gitignore_idx < commit_idx, (
        "the gitignore guarantee (step 1) must be documented BEFORE the "
        "commit (step 2), not after it"
    )


def test_gitignore_guarantee_folds_into_own_commit():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    final_m = re.search(r"## Final step.*", body, re.DOTALL)
    assert final_m, "SKILL.md must contain a '## Final step' section"
    final_step = final_m.group(0)
    gitignore_m = re.search(
        r"1\. \*\*Target-repo `\.gitignore` guarantee\*\*.*?(?=\n2\. \*\*Commit\*\*)",
        final_step, re.DOTALL,
    )
    assert gitignore_m, "must find the standalone gitignore-guarantee step"
    gitignore_step = gitignore_m.group(0)
    assert re.search(r"own commit|this run's own|properly attributed", gitignore_step, re.IGNORECASE), (
        "the gitignore guarantee must explain that, because it runs before "
        "the commit, an append becomes part of THIS run's own (properly "
        "attributed) commit rather than an uncommitted stray change"
    )
    assert not re.search(r"does not (retroactively )?protect.{0,80}this run", gitignore_step, re.IGNORECASE), (
        "the fixed ordering must NOT still claim the append doesn't protect "
        "the run that just wrote it — that was true only under the old, "
        "buggy post-commit ordering"
    )


def test_marker_step_gitignore_check_runs_in_both_modes():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    final_m = re.search(r"## Final step.*", body, re.DOTALL)
    assert final_m, "SKILL.md must contain a '## Final step' section"
    final_step = final_m.group(0)
    gitignore_m = re.search(
        r"1\. \*\*Target-repo `\.gitignore` guarantee\*\*.*?(?=\n2\. \*\*Commit\*\*)",
        final_step, re.DOTALL,
    )
    assert gitignore_m, "must find the standalone gitignore-guarantee step"
    assert re.search(r"both modes", gitignore_m.group(0), re.IGNORECASE), (
        "the target-repo .gitignore check/append must be documented as "
        "running in both solo and integration mode, matching the "
        "unconditional marker write itself"
    )


def test_result_marker_documents_json_fields():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    # Anchor to the ```json fenced block itself (Final step 6's marker
    # contents), not the first occurrence of the filename anywhere in the
    # doc — round 3 moved an earlier mention of the filename into Final
    # step 1's gitignore guarantee, which comes before the JSON contents and
    # would otherwise make a naive "first occurrence" search miss this block.
    marker_m = re.search(r"```json.{0,600}", body, re.DOTALL)
    assert marker_m, "must find the result-marker JSON contents block"
    marker_section = marker_m.group(0)
    assert re.search(r"APPROVE.{0,40}CHANGES_REQUESTED|CHANGES_REQUESTED.{0,40}APPROVE",
                      marker_section, re.DOTALL), (
        "the marker documentation must name the 'verdict' field's values "
        "(APPROVE / CHANGES_REQUESTED) near the marker filename, not merely "
        "somewhere else in the doc"
    )
    assert re.search(r"PASS.{0,20}FAIL|FAIL.{0,20}PASS", marker_section, re.DOTALL), (
        "the marker documentation must name the 'test' field's values "
        "(PASS / FAIL) near the marker filename, not merely somewhere else "
        "in the doc"
    )


# ---------------------------------------------------------------------------
# Group 7 — ticket #64 round 2, finding B: the marker must be gitignore-safe
# in an ARBITRARY target project repo, not just this plugin's own repo
# ---------------------------------------------------------------------------
#
# Root cause: round 1 added '.process-ticket-result.json' to THIS plugin
# repo's own .gitignore. But process-ticket always runs against an arbitrary
# target project repo supplied via project_id/worktree_path (see AGENTS.md's
# "Why the project id is always a parameter" — there is no "self" special
# case). This plugin's own .gitignore has zero effect there, so a subsequent
# `git add -A` in that target repo/worktree (e.g. on the next ticket
# processed there) could still sweep the marker into a real commit.
#
# Fix (round 2): checks/appends '.process-ticket-result.json' to the TARGET
# repo's own .gitignore, idempotently, in both modes.
#
# Round 3 correction: round 2 folded this check into the post-commit
# marker-write step, which reintroduced the round-3 finding-1 bug (see
# Group 6b above) — so these tests now anchor to the standalone, pre-commit
# "Target-repo `.gitignore` guarantee" step (Final step 1) instead of the
# marker-write step (Final step 6).
#
# Red -> green: these tests fail against the round-1 SKILL.md (which never
# mentions checking or writing to the target repo's .gitignore at all) and
# pass once Final step 1 documents the check-and-append ahead of the commit.


def _extract_gitignore_step(body: str) -> str:
    final_m = re.search(r"## Final step.*", body, re.DOTALL)
    assert final_m, "SKILL.md must contain a '## Final step' section"
    final_step = final_m.group(0)
    gitignore_m = re.search(
        r"1\. \*\*Target-repo `\.gitignore` guarantee\*\*.*?(?=\n2\. \*\*Commit\*\*)",
        final_step, re.DOTALL,
    )
    assert gitignore_m, "must find the standalone gitignore-guarantee step (Final step 1)"
    return gitignore_m.group(0)


def test_marker_step_checks_target_repo_gitignore_not_plugins_own():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    gitignore_step = _extract_gitignore_step(body)
    assert re.search(r"target repo'?s own `?\.gitignore`?", gitignore_step, re.IGNORECASE), (
        "the gitignore-guarantee step must explicitly check the TARGET repo's "
        "own '.gitignore', not just rely on this plugin's own '.gitignore'"
    )
    assert re.search(r"zero effect|no effect|has no effect", gitignore_step, re.IGNORECASE), (
        "the gitignore-guarantee step must explain that this plugin's own "
        "'.gitignore' has no effect on real usage against an arbitrary "
        "target repo"
    )


def test_marker_step_appends_gitignore_line_idempotently():
    text = _read(PROCESS_MD)
    body = _extract_body(text)
    gitignore_step = _extract_gitignore_step(body)
    assert re.search(r"append", gitignore_step, re.IGNORECASE), (
        "the gitignore-guarantee step must document appending the marker "
        "filename to the target repo's .gitignore when it's missing"
    )
    assert re.search(r"idempotent|check first", gitignore_step, re.IGNORECASE), (
        "the gitignore append must be documented as idempotent / check-first "
        "so re-running process-ticket never double-appends the line"
    )
    assert re.search(r"never touch|don'?t touch|not touch|never rewrite", gitignore_step, re.IGNORECASE), (
        "the gitignore append must be documented as leaving every other "
        "line in the target repo's .gitignore untouched"
    )
