"""
Regression tests for ticket #62: orchestrate-tickets reworked into a
wave-based fleet model with a shared integration branch.

Root cause: the pre-rework skill created one worktree per ticket off `base`,
in a single flat `parallel` batch, and then stopped — the user drove each
worktree's process-ticket run manually, with no shared integration branch,
no cross-wave merge gate, and no combined PR.

Rework: a shared integration branch is created off `base` at run start; each
wave's worktrees branch off the CURRENT integration-branch head (not `base`);
process-ticket runs per member in `mode=integration`; approved+green members
are merged `--no-ff` into the integration branch after a B4 clean-checkout
gate; a full-suite integration gate runs after each wave's merges; on GREEN
the integration branch is pushed (B1) before the next wave creates any
worktree; on RED the run STOPs with documented state (no auto-revert); at the
end of the run exactly one combined draft PR is opened. Teardown gets a
generalized process sweep (B2) and a force-unregister fallback (B3). SINGLE
mode still synthesizes a one-member, one-wave run through the same flow.

Red→green: these tests fail against the pre-rework SKILL.md (worktrees off
`base`, single flat `parallel` batch, no integration branch, no `--no-ff`
merge, no integration gate, per-ticket PRs, Codex-broker-only teardown sweep,
no force-unregister fallback) and pass after the rework.
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


# ---------------------------------------------------------------------------
# Group 1 — integration branch created off refreshed base
# ---------------------------------------------------------------------------


def test_creates_integration_branch():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "integration/" in body, (
        "SKILL.md must document creating an 'integration/<run-slug>' branch"
    )
    assert "git branch" in body, (
        "SKILL.md must document 'git branch' to create the integration branch"
    )


def test_integration_branch_pushed_once_at_start():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"integration.{0,300}push", body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document pushing the integration branch once at run start"
    )


# ---------------------------------------------------------------------------
# Group 2 — worktrees branch off the integration head, not base
# ---------------------------------------------------------------------------


def test_worktrees_branch_off_integration_head_not_base():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"integration.{0,80}(head|branch head|current head)", body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document worktrees branching off the CURRENT "
        "integration-branch head"
    )
    assert "not base" in body.lower() or "not `base`" in body.lower() or "not the base" in body.lower(), (
        "SKILL.md must explicitly say worktrees no longer branch off `base`"
    )


# ---------------------------------------------------------------------------
# Group 3 — waves iteration (not a single flat parallel batch)
# ---------------------------------------------------------------------------


def test_iterates_waves_array():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "waves" in body, (
        "SKILL.md must parse and iterate the analyst's 'waves' array"
    )
    assert re.search(r"wave.by.wave|wave.by.wave.in.order|iterate.{0,40}wave", body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document iterating wave-by-wave in order"
    )


def test_single_mode_synthesizes_one_wave():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"SINGLE.{0,200}(one|single|1)\s+wave", body, re.DOTALL), (
        "SKILL.md must document that SINGLE mode still synthesizes one wave "
        "so it flows through the same wave-based pipeline"
    )


# ---------------------------------------------------------------------------
# Group 4 — process-ticket invoked in integration mode per wave member
# ---------------------------------------------------------------------------


def test_invokes_process_ticket_integration_mode():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "mode=integration" in body, (
        "SKILL.md must invoke process-ticket with mode=integration for each "
        "wave member"
    )
    assert "worktree_path=" in body, (
        "SKILL.md must pass worktree_path= to each process-ticket invocation"
    )


# ---------------------------------------------------------------------------
# Group 5 — B4 clean-checkout gate before merge
# ---------------------------------------------------------------------------


def test_b4_clean_checkout_gate_before_merge():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "git status --porcelain" in body, (
        "SKILL.md must document the B4 clean-checkout gate using "
        "'git status --porcelain'"
    )
    assert re.search(r"clean.{0,120}before.{0,40}merge|before.{0,40}merge.{0,120}clean",
                      body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document the clean-checkout gate running BEFORE any merge"
    )


def test_checks_out_integration_branch_before_merge():
    """Regression for ticket #62 review round 2, finding 1: Phase C creates
    `<integration>` with `git branch <integration> <base>` (no checkout — the
    main checkout stays on `base`), and nothing before the `git merge --no-ff`
    step ever switches onto `<integration>`. As written, merges would land on
    `base` instead, so `<integration>` never actually receives the wave's
    changes. SKILL.md must document an explicit checkout/switch onto
    `<integration>` before the merge step.
    """
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c_m = re.search(r"## Phase C.*?(?=\n## Phase D)", body, re.DOTALL)
    assert phase_c_m, "SKILL.md must contain a '## Phase C' section"
    phase_c = phase_c_m.group(0)
    assert re.search(r"git\s+(checkout|switch)\s+<integration>", phase_c), (
        "Phase C must document an explicit 'git checkout <integration>' (or "
        "'git switch <integration>') on the main checkout before the merge "
        "step, otherwise 'git merge --no-ff' lands on whatever branch the "
        "main checkout is currently on (base), not <integration>"
    )
    checkout_m = re.search(r"git\s+(checkout|switch)\s+<integration>", phase_c)
    merge_m = re.search(r"git merge --no-ff", phase_c)
    assert merge_m, "Phase C must still document 'git merge --no-ff'"
    assert checkout_m.start() < merge_m.start(), (
        "The checkout/switch onto <integration> must be documented BEFORE "
        "the 'git merge --no-ff' step, not after"
    )


# ---------------------------------------------------------------------------
# Group 6 — --no-ff merge of approved + green members only
# ---------------------------------------------------------------------------


def test_merges_with_no_ff():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "--no-ff" in body, (
        "SKILL.md must document merging wave members with 'git merge --no-ff'"
    )


def test_merges_only_approved_and_green_members():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "APPROVE" in body, (
        "SKILL.md must gate the merge on the member having ended APPROVE"
    )
    assert re.search(r"unapproved|red\s+members|dropped", body, re.IGNORECASE), (
        "SKILL.md must document that unapproved/red members are dropped from "
        "the merge and roll into a later wave"
    )


# ---------------------------------------------------------------------------
# Group 7 — integration gate: full suite after merging
# ---------------------------------------------------------------------------


def test_integration_gate_runs_full_suite():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"integration gate", body, re.IGNORECASE), (
        "SKILL.md must name an 'integration gate' step"
    )
    assert re.search(r"full.{0,20}(test\s+)?suite", body, re.IGNORECASE), (
        "SKILL.md must document running the full detected test suite as the "
        "integration gate"
    )


# ---------------------------------------------------------------------------
# Group 8 — B1: push integration branch before next wave (green path)
# ---------------------------------------------------------------------------


def test_b1_push_before_next_wave():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"push.{0,200}before.{0,40}next\s+wave|before.{0,40}next\s+wave.{0,200}push",
                      body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document pushing the integration branch as a hard "
        "precondition before the next wave creates any worktree (B1)"
    )


# ---------------------------------------------------------------------------
# Group 9 — RED path: STOP, no auto-revert, documented state
# ---------------------------------------------------------------------------


def test_red_gate_stops_with_no_auto_revert():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"STOP\s+immediately", body, re.IGNORECASE), (
        "SKILL.md must document STOPping immediately on a RED integration gate"
    )
    assert re.search(r"no\s+automatic\s+revert|no\s+auto[- ]revert", body, re.IGNORECASE), (
        "SKILL.md must explicitly say there is no automatic revert on RED"
    )


def test_red_gate_leaves_worktrees_intact_and_unpushed_merge():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"unpushed", body, re.IGNORECASE), (
        "SKILL.md must document that the failed wave's merge commits stay "
        "local/unpushed"
    )
    assert re.search(r"worktrees.{0,120}(intact|skip\s+teardown)|intact.{0,120}worktrees",
                      body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document that the wave's worktrees are left intact "
        "(teardown skipped) for inspection on RED"
    )


def test_red_gate_reports_failure_details_to_user():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"which\s+wave\s+failed|failing\s+test\s+names", body, re.IGNORECASE), (
        "SKILL.md must document reporting which wave failed and the failing "
        "test names to the user on RED"
    )


# ---------------------------------------------------------------------------
# Group 10 — single combined draft PR at end of run
# ---------------------------------------------------------------------------


def test_single_draft_pr_head_is_integration_branch():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"head\s*=\s*<?integration", body, re.IGNORECASE), (
        "SKILL.md must document opening exactly one draft PR with "
        "head=<integration-branch>"
    )
    assert re.search(r"exactly\s+one|single\s+draft\s+pr", body, re.IGNORECASE), (
        "SKILL.md must say exactly ONE draft PR is opened at end of run"
    )


def test_pr_body_recaps_run_and_closes_every_ticket():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "Closes #" in body, (
        "SKILL.md must document the PR body containing 'Closes #<n>' for "
        "every processed ticket"
    )


def test_provider_portability_caveat_kept():
    """The existing AGENTS.md Provider-portability caveat about Closes# must be kept."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"Azure\s+DevOps|Jira", body), (
        "SKILL.md must keep the provider-portability caveat about 'Closes #' "
        "not being GitHub/GitLab-universal"
    )


def test_link_comment_posted_per_processed_ticket():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"one\s+link-comment\s+per\s+processed\s+ticket|link-comment.{0,60}per\s+ticket",
                      body, re.DOTALL | re.IGNORECASE), (
        "SKILL.md must document posting one link-comment per processed ticket "
        "at end of run"
    )


def test_switches_back_to_default_branch_at_end_of_phase_d():
    """Regression for ticket #62 review round 2, finding 1 (second half): once
    the main checkout is switched onto `<integration>` before the wave merge
    (see test_checks_out_integration_branch_before_merge), it must be switched
    back to the default branch at the end of Phase D — otherwise Precondition
    0 ("must be the repo's default branch") fails on the next invocation of
    this skill.
    """
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_d_m = re.search(r"## Phase D.*?(?=\n## Teardown)", body, re.DOTALL)
    assert phase_d_m, "SKILL.md must contain a '## Phase D' section"
    phase_d = phase_d_m.group(0)
    assert re.search(r"git\s+(checkout|switch)\s+<?base>?", phase_d, re.IGNORECASE), (
        "Phase D must document switching the main checkout back to the "
        "default branch ('git checkout <base>' or 'git switch <base>') after "
        "opening the combined PR, so Precondition 0 holds for the next run"
    )
    assert re.search(r"Precondition\s+0", phase_d), (
        "Phase D's switch-back step should explicitly reference Precondition "
        "0 so the connection to the guard it restores is documented"
    )


# ---------------------------------------------------------------------------
# Group 11 — B2: generalized worktree-bound-process sweep
# ---------------------------------------------------------------------------


def test_b2_generic_process_sweep_matches_worktree_path():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"any\s+process\s+whose\s+command", body, re.IGNORECASE) or \
        re.search(r"references\s+the\s+worktree\s+path", body, re.IGNORECASE), (
        "SKILL.md must generalize the teardown sweep to match ANY process "
        "whose command-line or cwd references the worktree path"
    )


def test_b2_names_serena_lsp_chain():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    for proc in ("serena.exe", "uvx", "python.exe"):
        assert proc in body, (
            f"SKILL.md must explicitly name '{proc}' in the generalized "
            "teardown process sweep (Serena LSP chain)"
        )


def test_b2_keeps_windows_and_posix_snippets():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert "Get-CimInstance Win32_Process" in body, (
        "SKILL.md must keep the Windows Get-CimInstance Win32_Process snippet"
    )
    assert "pkill -f" in body, (
        "SKILL.md must keep the POSIX pkill -f snippet"
    )


# ---------------------------------------------------------------------------
# Group 12 — B3: force-unregister fallback for phantom worktree entries
# ---------------------------------------------------------------------------


def test_b3_force_unregister_fallback_documented():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    assert re.search(r"force[- ]unregister", body, re.IGNORECASE), (
        "SKILL.md must document a 'force-unregister' fallback path in the "
        "phantom-entry recovery section"
    )
    assert re.search(r"same\s+(original\s+)?branch\s+name|reuse", body, re.IGNORECASE), (
        "SKILL.md must document that the force-unregister fallback frees the "
        "branch name for reuse under the SAME original branch name"
    )


# ---------------------------------------------------------------------------
# Group 13 — no stale pre-rework "create-and-stop" / "one PR per ticket" prose
# ---------------------------------------------------------------------------
#
# REGRESSION (#62 review pass): the frontmatter description and body intro
# still described the pre-rework "create the worktrees, and stop" /
# "each ticket gets its own PR" model after Phase C/D were rewritten to have
# the orchestrator itself drive the wave loop and open one combined PR. This
# is a fresh red->green pair: it fails against that stale wording and passes
# once the description/intro/fit-awareness section are rewritten.


def test_description_reflects_orchestrator_drives_fleet_to_one_pr():
    text = _read(ORCHESTRATE_MD)
    desc = re.search(r"^description:\s*(.*)$", text, re.MULTILINE).group(1)
    assert "mode=integration" in desc, (
        "orchestrate-tickets description must mention that the orchestrator "
        "itself drives process-ticket in mode=integration per wave"
    )
    assert re.search(r"one\s+combined\s+draft\s+pr", desc, re.IGNORECASE), (
        "orchestrate-tickets description must mention opening exactly one "
        "combined draft PR at the end of the run"
    )


def test_description_no_longer_says_one_worktree_per_ticket_only():
    text = _read(ORCHESTRATE_MD)
    desc = re.search(r"^description:\s*(.*)$", text, re.MULTILINE).group(1)
    assert "Creates one worktree per ticket." not in desc, (
        "orchestrate-tickets description must not reduce the skill's scope to "
        "just 'Creates one worktree per ticket' — it now drives the whole "
        "fleet through wave-based merges to a single combined PR"
    )


def test_body_intro_no_longer_says_create_worktrees_and_stop():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    intro = body[: body.index("## How to slice")]
    assert "create the worktrees, and stop" not in intro, (
        "SKILL.md body intro must not say the orchestrator 'creates the "
        "worktrees, and stops' — Phase C has the orchestrator itself drive "
        "process-ticket per wave member and merge/gate/push, and Phase D has "
        "it open the single combined PR"
    )
    assert re.search(r"user drives each worktree session independently", intro) is None, (
        "SKILL.md body intro must not say the user drives each worktree "
        "session independently — the orchestrator now drives the fleet "
        "end-to-end itself"
    )
    assert re.search(r"wave.by.wave|wave\s+by\s+wave", intro, re.IGNORECASE), (
        "SKILL.md body intro must describe the orchestrator driving the fleet "
        "wave by wave"
    )


def test_fit_section_no_longer_claims_one_pr_per_ticket():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    fit_section_m = re.search(
        r"## Fit-awareness.*?(?=\n## Inputs)", body, re.DOTALL
    )
    assert fit_section_m, "SKILL.md must contain the '## Fit-awareness' section"
    fit_section = fit_section_m.group(0)
    assert "each ticket gets its own worktree and its own PR" not in fit_section, (
        "Fit-awareness section must not claim each ticket gets its own PR — "
        "there is exactly one combined PR per run under the wave model"
    )
    assert re.search(
        r"each\s+ticket gets its own worktree and its own PR", fit_section
    ) is None, (
        "Fit-awareness section must not claim each ticket gets its own PR — "
        "there is exactly one combined PR per run under the wave model "
        "(whitespace-tolerant check, catches a line-wrapped 'each\\nticket')"
    )
    assert re.search(r"one\s+combined\s+PR|exactly\s+one.{0,20}PR", fit_section, re.IGNORECASE), (
        "Fit-awareness section must state the shared-integration-branch / "
        "single-PR model explicitly"
    )


def test_fit_section_high_ticket_count_signal_not_pr_overhead():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    fit_section_m = re.search(
        r"## Fit-awareness.*?(?=\n## Inputs)", body, re.DOTALL
    )
    assert fit_section_m, "SKILL.md must contain the '## Fit-awareness' section"
    fit_section = fit_section_m.group(0)
    assert "the fixed per-ticket overhead (worktree creation, PR overhead)" not in fit_section, (
        "The 'High ticket count with low parallelism' signal must not still "
        "attribute overhead to per-ticket PR overhead — PR count is fixed at "
        "one per run, not per ticket, under the wave model"
    )
