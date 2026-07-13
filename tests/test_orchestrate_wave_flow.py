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
PROCESS_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


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
    assert re.search(r"git\s+-C\s+<repo_root>\s+branch", body), (
        "SKILL.md must document 'git branch' (now -C-pinned per ticket #66) "
        "to create the integration branch"
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
    assert re.search(r"git\s+-C\s+<repo_root>\s+status\s+--porcelain", body), (
        "SKILL.md must document the B4 clean-checkout gate using "
        "'git status --porcelain' (now -C-pinned per ticket #66; the "
        "idle-fallback protocol's separate 'git -C <worktree_path> status "
        "--porcelain' is unaffected)"
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
    assert re.search(r"git\s+-C\s+<repo_root>\s+(checkout|switch)\s+<integration>", phase_c), (
        "Phase C must document an explicit 'git checkout <integration>' (or "
        "'git switch <integration>', now -C-pinned per ticket #66) on the "
        "main checkout before the merge step, otherwise 'git merge --no-ff' "
        "lands on whatever branch the main checkout is currently on (base), "
        "not <integration>"
    )
    checkout_m = re.search(r"git\s+-C\s+<repo_root>\s+(checkout|switch)\s+<integration>", phase_c)
    merge_m = re.search(r"git\s+-C\s+<repo_root>\s+merge --no-ff", phase_c)
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
    assert re.search(r"git\s+-C\s+<repo_root>\s+(checkout|switch)\s+<?base>?", phase_d, re.IGNORECASE), (
        "Phase D must document switching the main checkout back to the "
        "default branch ('git checkout <base>' or 'git switch <base>', now "
        "-C-pinned per ticket #66) after opening the combined PR, so "
        "Precondition 0 holds for the next run"
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


# ---------------------------------------------------------------------------
# Group 14 — ticket #64: idle-triggered git-state + marker fallback when a
# wave member's Final-step report never arrives
# ---------------------------------------------------------------------------
#
# Root cause: parallel wave members are necessarily background/named `Agent`
# spawns (required to run concurrently) — the same delivery mechanism whose
# failure mode caused the planner-spawn deadlock fixed in #58/#60. A member
# can finish all its real work (local commit, reviewer APPROVE) and still go
# idle without ever sending its mandated report back, making an otherwise-
# successful run look stalled. There was no documented fallback for this.
#
# Red -> green: these tests fail against the pre-#64 SKILL.md (no fallback
# documented at all) and pass once Phase C documents the idle-triggered
# git-state + result-marker fallback and the conservative non-merge rule.


def _extract_phase_c(body: str) -> str:
    phase_c_m = re.search(r"## Phase C.*?(?=\n## Phase D)", body, re.DOTALL)
    assert phase_c_m, "SKILL.md must contain a '## Phase C' section"
    return phase_c_m.group(0)


def test_phase_c_git_state_fallback_when_report_missing():
    """The required regression test: Phase C must document verifying a
    member's completion via `git -C <worktree_path>` directly, rather than
    relying solely on the worker's own self-report."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"git\s+-C\s+<worktree_path>\s+log", phase_c), (
        "Phase C must document 'git -C <worktree_path> log' as part of a "
        "fallback that verifies a member's completion directly"
    )
    assert re.search(r"git\s+-C\s+<worktree_path>\s+status\s+--porcelain", phase_c), (
        "Phase C must document 'git -C <worktree_path> status --porcelain' "
        "as part of the fallback"
    )
    assert re.search(r"self-report", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say the fallback does not rely solely on "
        "the worker's self-report"
    )


def test_fallback_is_idle_triggered():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"idle", phase_c, re.IGNORECASE), (
        "Phase C must tie the fallback trigger to a member going idle"
    )
    assert re.search(r"timer.free|no\s+timer|not\s+.{0,20}timer|without\s+.{0,20}timer", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say the check is NOT timer-based — the "
        "orchestrator has no timer"
    )


def test_fallback_trigger_excludes_already_reported_members():
    """Regression for ticket #64 review round 1, finding 5: the documented
    trigger is "idle WITHOUT having sent its Final-step report" — a member
    that reports first and then goes idle (the fast, successful path) must
    NOT re-trigger the fallback. The prose must scope the trigger explicitly,
    not merely say "idle" on its own.
    """
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"without\*{0,2}\s+having\s+sent\s+its\s+Final-step\s+report", phase_c, re.IGNORECASE), (
        "Phase C must scope the fallback trigger to idle-WITHOUT-having-sent-"
        "its-report, not idle alone"
    )
    assert re.search(
        r"reports?\s+first.{0,80}(then\s+)?goes?\s+idle.{0,80}not.{0,20}(re-)?trigger|"
        r"not.{0,20}re-trigger.{0,120}reports?\s+first",
        phase_c, re.DOTALL | re.IGNORECASE,
    ), (
        "Phase C must explicitly say that a member which reports first and "
        "then goes idle does NOT re-trigger the fallback — the fast/"
        "successful path must be excluded from the trigger"
    )


def test_fallback_uses_path_explicit_git_c():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert "git -C <worktree_path>" in phase_c, (
        "Phase C's fallback must use 'git -C <worktree_path>', not a bare "
        "cwd-relative git command"
    )


def test_fallback_reads_result_marker_for_verdict():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert ".process-ticket-result.json" in phase_c, (
        "Phase C must document reading '.process-ticket-result.json' to "
        "recover the reviewer verdict and test result"
    )


def test_unconfirmed_member_not_merged_rolls_to_later_wave():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"not\s+merged", phase_c, re.IGNORECASE), (
        "Phase C must document that an unconfirmed member is NOT merged"
    )
    assert re.search(r"later\s+wave", phase_c, re.IGNORECASE), (
        "Phase C must document that an unconfirmed member rolls into a "
        "later wave"
    )


def test_phase_c_documents_background_spawn_report_can_drop():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"#58|#60", phase_c), (
        "Phase C must cross-reference the #58/#60 planner-spawn deadlock as "
        "the root cause of the same class of bug"
    )
    assert re.search(r"background|named.{0,20}spawn|mailbox", phase_c, re.IGNORECASE), (
        "Phase C must document that parallel wave members are necessarily "
        "background/named Agent spawns whose report can silently drop"
    )


def test_agents_md_documents_b6_report_loss_fallback():
    text = _read(AGENTS_MD)
    assert re.search(r"\bB6\b", text), (
        "AGENTS.md must document a 'B6' safeguard for the wave-member "
        "report-loss fallback"
    )
    assert ".process-ticket-result.json" in text, (
        "AGENTS.md must reference the '.process-ticket-result.json' marker "
        "file in the B6 note"
    )
    assert re.search(r"idle", text, re.IGNORECASE), (
        "AGENTS.md's B6 note must mention the idle-triggered fallback"
    )


def test_marker_filename_consistent_across_skills():
    orchestrate_body = _extract_body(_read(ORCHESTRATE_MD))
    process_body = _extract_body(_read(PROCESS_MD))
    assert ".process-ticket-result.json" in orchestrate_body, (
        "skills/orchestrate-tickets/SKILL.md must reference "
        "'.process-ticket-result.json'"
    )
    assert ".process-ticket-result.json" in process_body, (
        "skills/process-ticket/SKILL.md must reference "
        "'.process-ticket-result.json'"
    )


# ---------------------------------------------------------------------------
# Group 15 — ticket #64 round 2, finding D: dedicated test for the
# non-merge rule's `test`-field disqualification specifically
# ---------------------------------------------------------------------------
#
# Root cause: round 1's tests only ever asserted generic "not merged"/"later
# wave" phrasing (test_unconfirmed_member_not_merged_rolls_to_later_wave).
# None of them pinned down that the Conservative non-merge rule disqualifies
# on the marker's `test` field specifically, not just `verdict` — a
# verdict-only fallback (silently weaker than the normal merge path, which
# requires APPROVE *with* a green test run) would have slipped past every
# existing assertion undetected.
#
# Red -> green: this test fails against a hypothetical verdict-only rewrite
# of the Conservative non-merge rule (asserted below via a literal
# "old wording" string that satisfies every *existing* non-merge assertion
# but not this one) and passes against the current SKILL.md, which
# explicitly ties disqualification to the marker's `test` field not being
# `PASS`.


def test_conservative_non_merge_rule_checks_test_field_not_just_verdict():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)

    # A hypothetical verdict-only rewrite of the rule: it says "not merged"
    # and "later wave" (satisfying the OLD, generic assertions in
    # test_unconfirmed_member_not_merged_rolls_to_later_wave above) but never
    # mentions the marker's `test` field at all.
    verdict_only_wording = (
        "A member whose ending state cannot be confirmed this way is not "
        "merged: HEAD not ahead of the branch point, the marker file "
        "missing or unreadable, or the marker's verdict is not APPROVE — "
        "any one of these disqualifies the member. A disqualified member "
        "rolls into a later wave, exactly like today's CHANGES_REQUESTED/"
        "red members."
    )
    assert re.search(r"not\s+merged", verdict_only_wording, re.IGNORECASE)
    assert re.search(r"later\s+wave", verdict_only_wording, re.IGNORECASE)

    test_field_pattern = r"marker'?s?\s+`test`\s+(is\s+)?not\s+`PASS`"

    # Confirm the test-field pattern genuinely distinguishes the two: the
    # verdict-only wording must NOT satisfy it (proves this is a real
    # red->green check, not a tautology that any wording would pass).
    assert not re.search(test_field_pattern, verdict_only_wording, re.IGNORECASE), (
        "sanity check failed: the verdict-only wording unexpectedly matched "
        "the test-field pattern, which would make this test meaningless"
    )

    # The real SKILL.md must satisfy the stronger, test-field-specific check.
    assert re.search(test_field_pattern, phase_c, re.IGNORECASE), (
        "Phase C's Conservative non-merge rule must explicitly disqualify a "
        "member whose marker `test` field is not `PASS` — checking `verdict` "
        "alone is not sufficient, since the ordinary (non-fallback) merge "
        "criterion is APPROVE *with* a green test run, so a verdict-only "
        "fallback would be silently weaker than the normal merge path"
    )


# ---------------------------------------------------------------------------
# Group 16 — ticket #64 round 2, finding C: the marker must be validated as
# belonging to THIS run/member, not blindly trusted
# ---------------------------------------------------------------------------
#
# Root cause: the Phase C fallback read the result-marker file but never
# checked it actually belongs to *this* run. Since RED waves deliberately
# keep worktrees intact (no auto-revert), a worktree could be reused or
# retried, and a stale marker from an earlier attempt could be misread as
# confirming a retry that produced no real new work.
#
# Fix: the marker is only trusted after the HEAD-ahead-of-branch-point check
# has already proven a genuine new commit landed, AND the marker's `ticket`
# field must match the wave member's actual ticket number — a mismatch is
# rejected and treated as unconfirmed, same as a missing marker.
#
# Red -> green: fails against the round-1 SKILL.md (marker read immediately
# after the HEAD-ahead check with no `ticket`-field cross-check at all) and
# passes once Phase C documents the staleness/ticket-match check.


def test_marker_ticket_field_must_match_member_ticket():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"`ticket`\s+field", phase_c, re.IGNORECASE), (
        "Phase C must document checking the marker's `ticket` field"
    )
    assert re.search(
        r"`ticket`\s+field.{0,200}(match|equal)|"
        r"(match|equal).{0,200}`ticket`\s+field",
        phase_c, re.DOTALL | re.IGNORECASE,
    ), (
        "Phase C must document that the marker's `ticket` field must match "
        "this wave member's actual ticket number"
    )
    assert re.search(r"stale", phase_c, re.IGNORECASE), (
        "Phase C must call a ticket-field mismatch a stale marker"
    )


def test_marker_only_trusted_after_head_ahead_check():
    """The staleness fix must tie marker trust to the already-proven
    HEAD-ahead-of-branch-point fact, not read the marker unconditionally."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    head_ahead_idx = phase_c.find("rev-list")
    marker_read_idx = phase_c.find("read the result-marker file")
    assert head_ahead_idx != -1, "Phase C must document the rev-list HEAD-ahead check"
    assert marker_read_idx != -1, (
        "Phase C must document reading the result-marker file with the "
        "phrase 'read the result-marker file' (distinct from the earlier, "
        "incidental mention of the marker filename in the 'status "
        "--porcelain' bullet, which merely notes it's expected to be absent "
        "since the marker is gitignored by the time it's written)"
    )
    assert head_ahead_idx < marker_read_idx, (
        "the HEAD-ahead-of-branch-point check must be documented BEFORE the "
        "marker file is read, so the marker is only trusted once a genuine "
        "new commit has already been proven"
    )
    assert re.search(r"only.{0,20}after|not\s+trusted\s+on\s+its\s+own", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say the marker is only read/trusted AFTER "
        "the HEAD-ahead check, not merely happen to be documented after it"
    )


def test_ticket_mismatch_disqualifies_member_from_merge():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    non_merge_m = re.search(r"\*\*Conservative non-merge rule\.\*\*.*", phase_c, re.DOTALL)
    assert non_merge_m, "Phase C must contain the 'Conservative non-merge rule'"
    non_merge_rule = non_merge_m.group(0)
    assert re.search(r"`ticket`\s+field\s+not\s+matching|not\s+matching.{0,60}`ticket`",
                      non_merge_rule, re.IGNORECASE), (
        "the Conservative non-merge rule must list a `ticket`-field mismatch "
        "as a disqualifying condition, alongside HEAD-not-ahead, missing "
        "marker, verdict-not-APPROVE, and test-not-PASS"
    )


def test_agents_md_documents_ticket_field_staleness_check():
    text = _read(AGENTS_MD)
    assert re.search(r"`ticket`\s+field", text, re.IGNORECASE), (
        "AGENTS.md's B6 note must document the marker's `ticket` field "
        "staleness check"
    )
    assert re.search(r"stale", text, re.IGNORECASE), (
        "AGENTS.md's B6 note must call a mismatched marker a stale marker"
    )


def test_agents_md_documents_target_repo_gitignore_fix():
    text = _read(AGENTS_MD)
    assert re.search(r"target repo'?s own\*{0,4}\s*`?\.gitignore`?", text, re.IGNORECASE), (
        "AGENTS.md must document that the real gitignore fix targets the "
        "TARGET repo's own .gitignore, not this plugin's own .gitignore"
    )


# ---------------------------------------------------------------------------
# Group 17 — ticket #64 round 3, finding 2: Phase C must NOT claim the marker
# shows up as `??` in plain `status --porcelain` output
# ---------------------------------------------------------------------------
#
# Root cause: round 2's Phase C fallback said to expect `status --porcelain`
# to show `?? .process-ticket-result.json` "even on a fully successful run."
# But round 3 finding 1 moved the target-repo .gitignore append to BEFORE
# process-ticket's own commit (see skills/process-ticket/SKILL.md's Final
# step 1), so by the time the marker file is written it is already
# gitignored — and a gitignored untracked file produces NO entry at all in
# plain `git status --porcelain` (verified: empty, not a `??` line). The old
# "expect `??`" claim is therefore factually wrong under the corrected
# ordering and must be corrected to "expect it to be absent."
#
# Red -> green: this test fails against the round-2 SKILL.md (which asserts
# the marker shows up as `?? .process-ticket-result.json`) and passes once
# Phase C instead documents the marker's absence from plain `status
# --porcelain` output.


def test_phase_c_does_not_claim_marker_shows_as_untracked_porcelain_entry():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert not re.search(r"\?\?\s*\.process-ticket-result\.json", phase_c), (
        "Phase C must NOT claim 'git status --porcelain' shows "
        "'?? .process-ticket-result.json' — once the target-repo .gitignore "
        "append runs before the commit (round 3 finding 1), the marker is "
        "already gitignored when written and produces no 'status "
        "--porcelain' entry at all, so the old '??' claim is now false"
    )
    assert re.search(r"absent|no\s+entry|not\s+(show|appear)", phase_c, re.IGNORECASE), (
        "Phase C must instead document that the marker is expected to be "
        "ABSENT from plain 'status --porcelain' output on a successful run"
    )
    assert re.search(r"gitignor", phase_c, re.IGNORECASE), (
        "Phase C must explain the marker's absence from 'status --porcelain' "
        "in terms of it already being gitignored by the time it's written"
    )


def test_agents_md_does_not_claim_marker_shows_as_untracked_porcelain_entry():
    """Cross-check AGENTS.md's B6 paragraph for the same now-false claim."""
    text = _read(AGENTS_MD)
    assert not re.search(r"\?\?\s*\.process-ticket-result\.json", text), (
        "AGENTS.md's B6 note must NOT claim the marker shows up as "
        "'?? .process-ticket-result.json' in 'status --porcelain' output"
    )


# ---------------------------------------------------------------------------
# Group 18 — ticket #64 round 3, finding 3: the Hard Rules summary bullet
# must list all 5 disqualifying conditions, including ticket-mismatch
# ---------------------------------------------------------------------------
#
# Root cause: the '## Hard rules' section's "Never merge on self-report
# alone (B6)" bullet restates the Conservative non-merge rule for quick
# reference, but only listed 4 conditions (HEAD not ahead, missing/unreadable
# marker, verdict not APPROVE, test not PASS) — missing the 5th condition
# (marker `ticket` field not matching the wave member's actual ticket
# number) that round 2 finding C added to Phase C step 2 and AGENTS.md's B6
# paragraph. All three restatements must list the same 5 conditions.
#
# Red -> green: this test fails against a Hard Rules bullet that lists only
# 4 conditions and passes once it lists the ticket-mismatch condition too.


def _extract_hard_rules(body: str) -> str:
    hard_rules_m = re.search(r"## Hard rules.*", body, re.DOTALL)
    assert hard_rules_m, "SKILL.md must contain a '## Hard rules' section"
    return hard_rules_m.group(0)


def test_hard_rules_b6_bullet_lists_all_five_disqualifying_conditions():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    hard_rules = _extract_hard_rules(body)
    b6_m = re.search(r"\*\*Never merge on self-report alone \(B6\)\.\*\*.*", hard_rules, re.DOTALL)
    assert b6_m, "Hard rules must contain the 'Never merge on self-report alone (B6)' bullet"
    b6_bullet = b6_m.group(0)
    # Stop at the next top-level bullet so we don't accidentally read past
    # the B6 bullet into unrelated Hard Rules text below it.
    next_bullet_m = re.search(r"\n- \*\*", b6_bullet)
    if next_bullet_m:
        b6_bullet = b6_bullet[: next_bullet_m.start()]
    assert re.search(r"HEAD\s+not\s+ahead", b6_bullet, re.IGNORECASE), (
        "the B6 Hard Rules bullet must list 'HEAD not ahead of the branch "
        "point' as a disqualifying condition"
    )
    assert re.search(r"missing.{0,20}unreadable\s+marker|marker.{0,20}missing", b6_bullet, re.IGNORECASE | re.DOTALL), (
        "the B6 Hard Rules bullet must list the missing/unreadable marker as "
        "a disqualifying condition"
    )
    assert re.search(r"`ticket`\s+not\s+matching|ticket.{0,60}matching", b6_bullet, re.IGNORECASE | re.DOTALL), (
        "the B6 Hard Rules bullet must list the marker `ticket` field not "
        "matching this member's actual ticket number as a disqualifying "
        "condition — this 5th condition was missing in round 2's summary "
        "bullet even though Phase C step 2 and AGENTS.md's B6 paragraph "
        "both correctly list it"
    )
    assert re.search(r"verdict.{0,20}not\s+`?APPROVE`?", b6_bullet, re.IGNORECASE | re.DOTALL), (
        "the B6 Hard Rules bullet must list marker `verdict` not `APPROVE` "
        "as a disqualifying condition"
    )
    assert re.search(r"test.{0,20}not\s+`?PASS`?", b6_bullet, re.IGNORECASE | re.DOTALL), (
        "the B6 Hard Rules bullet must list marker `test` not `PASS` as a "
        "disqualifying condition"
    )


# ---------------------------------------------------------------------------
# Group 19 — ticket #69: confirmed-done short-circuit for post-report idle
# pings
# ---------------------------------------------------------------------------
#
# Root cause: during live orchestrate-tickets runs (named/background Agent
# spawns per wave member, Phase C), a worker that has already sent its
# complete Final-step report keeps emitting idle_notification
# (idleReason: "available") pings afterward. Each ping carries zero new info
# but costs the orchestrator a message-read + "is this the B6 trigger?"
# reasoning step. This is not a correctness bug — it's the harmless mirror of
# #64's idle-without-report case — but it must be documented so the
# orchestrator can cheaply short-circuit it WITHOUT weakening the #64 B6
# idle-without-report fallback (which must still fire whenever a member goes
# idle before its report arrives).
#
# Fix: Phase C step 2 documents a confirmed-done set. A member enters it the
# moment its Final-step report is received, or — via the B6 fallback — the
# moment its ending state is confirmed (HEAD-ahead check passed and the
# result-marker validated). Any subsequent idle_notification from a member
# already in the confirmed-done set is a cheap set-membership no-op —
# acknowledge and discard it; it is NOT a fresh B6 evaluation. The Hard Rules
# B6 bullet and AGENTS.md's B6 paragraph both mirror this addition.
#
# Red -> green: these tests fail against the pre-#69 SKILL.md/AGENTS.md (no
# confirmed-done set documented at all) and pass once Phase C, the Hard Rules
# B6 bullet, and AGENTS.md's B6 paragraph all document the short-circuit.


def test_phase_c_documents_confirmed_done_short_circuit_for_post_report_idle():
    """The required regression test: Phase C must document a confirmed-done
    set and that a subsequent idle ping from an already-confirmed-done member
    is a no-op, not a fresh B6 evaluation."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"confirmed[- ]done", phase_c, re.IGNORECASE), (
        "Phase C must document a 'confirmed-done' set that a member enters "
        "once its Final-step report is received or the B6 fallback confirms "
        "its ending state"
    )
    assert re.search(
        r"(no-op|set.membership|not\s+a\s+fresh|already.{0,40}confirmed)"
        r".{0,160}(idle|B6)|"
        r"idle.{0,160}(no-op|not\s+a\s+fresh\s+B6|set.membership)",
        phase_c, re.DOTALL | re.IGNORECASE,
    ), (
        "Phase C must explicitly say a subsequent idle ping from a "
        "confirmed-done member is a cheap no-op / set-membership check, not "
        "a fresh B6 evaluation"
    )


def test_phase_c_short_circuit_does_not_weaken_b6_trigger():
    """The confirmed-done short-circuit must NOT weaken or replace the #64
    B6 idle-WITHOUT-report trigger — that phrasing must survive verbatim."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"without\*{0,2}\s+having\s+sent\s+its\s+Final-step\s+report", phase_c, re.IGNORECASE), (
        "Phase C must still scope the B6 fallback trigger to idle-WITHOUT-"
        "having-sent-its-report — the confirmed-done short-circuit must not "
        "weaken this"
    )


def test_hard_rules_b6_bullet_mentions_confirmed_done_short_circuit():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    hard_rules = _extract_hard_rules(body)
    b6_m = re.search(r"\*\*Never merge on self-report alone \(B6\)\.\*\*.*", hard_rules, re.DOTALL)
    assert b6_m, "Hard rules must contain the 'Never merge on self-report alone (B6)' bullet"
    b6_bullet = b6_m.group(0)
    next_bullet_m = re.search(r"\n- \*\*", b6_bullet)
    if next_bullet_m:
        b6_bullet = b6_bullet[: next_bullet_m.start()]
    assert re.search(r"confirmed[- ]done", b6_bullet, re.IGNORECASE), (
        "the B6 Hard Rules bullet must mention the 'confirmed-done' "
        "short-circuit for post-report idle pings"
    )
    assert re.search(r"no-op|set.membership", b6_bullet, re.IGNORECASE), (
        "the B6 Hard Rules bullet must say a later idle ping from an "
        "already-confirmed-done member is a no-op, never a re-triggered B6 "
        "check"
    )


def test_agents_md_documents_confirmed_done_short_circuit():
    text = _read(AGENTS_MD)
    assert re.search(r"confirmed[- ]done", text, re.IGNORECASE), (
        "AGENTS.md must document the 'confirmed-done' set introduced by "
        "ticket #69"
    )
    assert re.search(
        r"(no-op|set.membership).{0,160}B6|B6.{0,160}(no-op|set.membership)",
        text, re.DOTALL | re.IGNORECASE,
    ), (
        "AGENTS.md must say further idle pings from a confirmed-done member "
        "are a no-op set-membership check, not a repeated B6 evaluation"
    )
    assert not re.search(r"\?\?\s*\.process-ticket-result\.json", text), (
        "AGENTS.md must NOT reintroduce the false claim that the marker "
        "shows up as '?? .process-ticket-result.json' in 'status "
        "--porcelain' output"
    )


# ---------------------------------------------------------------------------
# Group 20 — ticket #68: B6 status-check ping disambiguates busy vs. dead
# before disqualifying
# ---------------------------------------------------------------------------
#
# Root cause: the B6 idle-without-report fallback (#64) made its merge/
# no-merge decision purely from a git-state snapshot. In a live run this
# wrongly demoted a healthy wave member that was still mid-pipeline (Phase 4
# review, waiting on its own nested reviewer sub-agent reply) — the git-state
# check came back unconfirmed even though the member was legitimately busy,
# not dead.
#
# Fix: before the Conservative non-merge rule disqualifies such a member,
# Phase C now documents a sanctioned single-ping `SendMessage` status check.
# It fires only when the member is on the already-narrow B6 trigger AND the
# git-state check came back unconfirmed. A coherent progress reply keeps the
# member eligible (not merged, not disqualified, not added to the
# confirmed-done set); an empty/error/incoherent reply, or the member's very
# next signal being another idle-without-report, falls through to the
# existing Conservative non-merge rule unchanged. The bound is single ping,
# reply-or-next-idle — no wall-clock timeout, no retry count — consistent
# with the pre-existing timer-free invariant. None of the #64 git-state
# criteria are relaxed.
#
# Red -> green: these tests fail against the pre-#68 SKILL.md/AGENTS.md (no
# status-check ping documented at all — the git-state snapshot alone decides
# merge/no-merge) and pass once Phase C, the Hard Rules B6 bullet, and
# AGENTS.md's B6 subsection all document the ping.


def _extract_ping_first_paragraph(phase_c: str) -> str:
    """Extract just the B6 status-check ping sub-step's opening paragraph
    (the one stating the firing condition and the git-state-passed/never-
    pinged outcome) — narrower than the whole Phase C block, so a proximity
    assertion against this substring can't be satisfied by the two phrases
    appearing anywhere unrelated in Phase C."""
    ping_m = re.search(r"\*\*B6 status-check ping.*?(?=\n\n)", phase_c, re.DOTALL)
    assert ping_m, "Phase C must contain the B6 status-check ping sub-step"
    return ping_m.group(0)


def _extract_ping_substep(phase_c: str) -> str:
    """Extract the FULL B6 status-check ping sub-step (opening paragraph +
    Bound/Outcomes text), from '**B6 status-check ping' through (not
    including) the '**Conservative non-merge rule.**' paragraph — wider than
    `_extract_ping_first_paragraph` (which stops at the first blank line),
    needed because the 'Send no second ping' sentence sits in the Outcomes
    bullet list, a later paragraph of the same sub-step. Still narrower than
    the whole Phase C block."""
    ping_m = re.search(
        r"\*\*B6 status-check ping.*?(?=\n\s*\*\*Conservative non-merge rule)",
        phase_c, re.DOTALL,
    )
    assert ping_m, "Phase C must contain the B6 status-check ping sub-step"
    return ping_m.group(0)


def _extract_b6_section(text: str) -> str:
    """Extract just the AGENTS.md B6 subsection (from its opening '**B6 —
    idle-triggered report-loss fallback' heading through the end of the
    section, immediately before the 'Cross-file consistency invariant'
    paragraph) — the AGENTS.md analogue of `_extract_phase_c`/
    `_extract_hard_rules`, so B6-subsection-specific assertions can't be
    satisfied by a stray/duplicate mention of the same wording elsewhere in
    the file."""
    b6_m = re.search(
        r"\*\*B6.{0,3}idle-triggered report-loss fallback.*?"
        r"(?=\n\*\*Cross-file consistency invariant)",
        text, re.DOTALL,
    )
    assert b6_m, "AGENTS.md must contain the B6 subsection"
    return b6_m.group(0)


def test_phase_c_documents_status_check_ping_before_conservative_rule():
    """The required regression test: Phase C must document a single-ping
    SendMessage status check, positioned BEFORE the Conservative non-merge
    rule so it has a chance to keep a busy-but-alive member from being
    wrongly disqualified."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    ping_idx = phase_c.find("status-check")
    non_merge_idx = phase_c.find("**Conservative non-merge rule.**")
    assert ping_idx != -1, (
        "Phase C must document a 'status-check' ping sub-step"
    )
    assert non_merge_idx != -1, (
        "Phase C must still contain the Conservative non-merge rule"
    )
    assert ping_idx < non_merge_idx, (
        "the status-check ping sub-step must be documented BEFORE the "
        "Conservative non-merge rule, so it gets a chance to keep a "
        "busy-but-alive member eligible before disqualification"
    )
    assert re.search(r"`SendMessage`", phase_c), (
        "Phase C must document the ping as a `SendMessage` call"
    )
    assert re.search(r"exactly\s+one", phase_c, re.IGNORECASE), (
        "Phase C must say the orchestrator sends exactly one status-check "
        "ping"
    )


def test_status_check_ping_fires_only_when_git_state_unconfirmed():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    ping_para = _extract_ping_first_paragraph(phase_c)
    assert re.search(r"never\s+pinged", ping_para, re.IGNORECASE), (
        "Phase C must document that a member whose git-state check PASSED "
        "is confirmed-done as usual and is never pinged"
    )
    # Tightened (ticket #68 review round 1, Codex finding 1): the "never
    # pinged" outcome must be textually TIED to the unconfirmed-gating
    # precondition, not merely present somewhere in the same Phase C block.
    # This single regex requires the "unconfirmed" gating clause to be
    # immediately followed (within a bounded window, no paragraph break) by
    # the "git-state check passed -> confirmed-done -> never pinged" clause
    # — an edit that kept the words "never pinged" but detached them from
    # the unconfirmed-gating condition (e.g. moved to an unrelated
    # sentence) would fail this.
    assert re.search(
        r"unconfirmed\*{0,2}.{0,260}\*{0,2}passed\*{0,2}\s+is\s+confirmed-done"
        r".{0,80}\*{0,2}never\s+pinged\*{0,2}",
        ping_para, re.IGNORECASE | re.DOTALL,
    ), (
        "Phase C must tie 'never pinged' directly to the git-state-check-"
        "passed / confirmed-done outcome, which must itself appear close "
        "after the unconfirmed-gating precondition within the same "
        "clause/paragraph window — detaching 'never pinged' from that "
        "precondition must fail this test"
    )


def test_status_check_ping_is_single_ping_no_timer_no_retry():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"no\s+wall-clock\s+timeout", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say the ping introduces no wall-clock "
        "timeout"
    )
    assert re.search(r"no\s+retry\s+count", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say the ping introduces no retry-count "
        "number"
    )
    assert re.search(r"reply-or-next-idle", phase_c, re.IGNORECASE), (
        "Phase C must bound the ping as single-ping, reply-or-next-idle"
    )


def test_coherent_reply_keeps_member_eligible_not_merged_not_confirmed_done():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"coherent\s+progress\s+reply", phase_c, re.IGNORECASE), (
        "Phase C must document the 'coherent progress reply' outcome"
    )
    assert re.search(
        r"do\s+not\s+disqualify.{0,40}do\s+not\s+merge", phase_c,
        re.IGNORECASE | re.DOTALL,
    ), (
        "Phase C must say a coherent reply means: do not disqualify, do "
        "not merge yet"
    )
    assert re.search(
        r"not\*{0,2}\s+added\s+to\s+the\s+confirmed-done\s+set", phase_c,
        re.IGNORECASE,
    ), (
        "Phase C must explicitly say a coherent-reply member is NOT added "
        "to the confirmed-done set — it is kept alive, not confirmed"
    )
    # Added (ticket #68 review round 1, follow-up finding): the "no second
    # ping after a coherent reply" invariant is a distinct, load-bearing
    # part of the plan's bound and was not asserted by any of the original
    # 9 tests — a future edit could reintroduce re-pinging a coherent-reply
    # member on its next idle signal and every existing test would stay
    # green. Scope to the full ping sub-step (the "Send no second ping"
    # sentence sits in the Outcomes bullet, past the first-paragraph cutoff
    # `_extract_ping_first_paragraph` uses).
    ping_substep = _extract_ping_substep(phase_c)
    assert re.search(r"no\s+second\s+ping", ping_substep, re.IGNORECASE), (
        "Phase C's coherent-reply outcome must explicitly say 'no second "
        "ping' is sent in response to a coherent reply"
    )


def test_incoherent_or_next_idle_falls_through_to_conservative_rule():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(
        r"empty\s+or\s+error\s+reply.{0,120}incoherent\s+reply.{0,160}"
        r"idle-without-report", phase_c, re.IGNORECASE | re.DOTALL,
    ), (
        "Phase C must document that an empty/error reply, an incoherent "
        "reply, or the member's next idle-without-report signal falls "
        "through to the Conservative non-merge rule"
    )
    assert re.search(r"falls\s+through", phase_c, re.IGNORECASE), (
        "Phase C must use fall-through language for the disqualifying "
        "outcomes"
    )


def test_status_check_ping_never_relaxes_git_state_criteria():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"never\s+relaxes", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say the ping never relaxes the existing "
        "git-state criteria or the Conservative non-merge rule"
    )


def test_hard_rules_b6_bullet_mentions_status_check_ping():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    hard_rules = _extract_hard_rules(body)
    b6_m = re.search(r"\*\*Never merge on self-report alone \(B6\)\.\*\*.*", hard_rules, re.DOTALL)
    assert b6_m, "Hard rules must contain the 'Never merge on self-report alone (B6)' bullet"
    b6_bullet = b6_m.group(0)
    next_bullet_m = re.search(r"\n- \*\*", b6_bullet)
    if next_bullet_m:
        b6_bullet = b6_bullet[: next_bullet_m.start()]
    assert re.search(r"status-check", b6_bullet, re.IGNORECASE), (
        "the B6 Hard Rules bullet must mention the status-check ping "
        "disambiguation step"
    )
    assert re.search(r"`SendMessage`", b6_bullet), (
        "the B6 Hard Rules bullet must name SendMessage as the ping "
        "mechanism"
    )
    assert re.search(r"never\s+relax", b6_bullet, re.IGNORECASE), (
        "the B6 Hard Rules bullet must say the ping never relaxes the "
        "git-state criteria"
    )


def test_agents_md_documents_status_check_ping_before_conservative_rule():
    text = _read(AGENTS_MD)
    b6_section = _extract_b6_section(text)
    # Tightened (ticket #68 review round 1, Codex finding 2): scope every
    # sub-assertion to the extracted B6 subsection, not the whole file — a
    # stray/duplicate mention of this wording elsewhere in AGENTS.md must
    # not be able to satisfy these checks.
    ping_idx = b6_section.find("Status-check ping")
    non_merge_idx = b6_section.find("**Conservative non-merge rule:**")
    assert ping_idx != -1, (
        "AGENTS.md's B6 subsection must document the status-check ping"
    )
    assert non_merge_idx != -1, (
        "AGENTS.md's B6 subsection must still contain the Conservative "
        "non-merge rule"
    )
    assert ping_idx < non_merge_idx, (
        "AGENTS.md's B6 subsection must document the status-check ping "
        "BEFORE the Conservative non-merge rule clause"
    )
    assert re.search(r"`SendMessage`", b6_section), (
        "AGENTS.md's B6 subsection must document the ping as a SendMessage "
        "call"
    )
    assert re.search(r"reply-or-next-idle", b6_section, re.IGNORECASE), (
        "AGENTS.md's B6 subsection must bound the ping as single-ping, "
        "reply-or-next-idle"
    )
    assert re.search(r"no\s+wall-clock\s+timeout", b6_section, re.IGNORECASE), (
        "AGENTS.md's B6 subsection must say the ping introduces no "
        "wall-clock timeout"
    )
    assert re.search(r"no\s+retry-count\s+number", b6_section, re.IGNORECASE), (
        "AGENTS.md's B6 subsection must say the ping introduces no "
        "retry-count number"
    )


def test_agents_md_coherent_reply_not_added_to_confirmed_done_set():
    text = _read(AGENTS_MD)
    # Tightened (ticket #68 review round 1, Codex finding 2): scope to the
    # extracted B6 subsection, not the whole file, so a stray/duplicate
    # mention elsewhere in AGENTS.md can't satisfy this check.
    b6_section = _extract_b6_section(text)
    assert re.search(
        r"not\*{0,2}\s+added\s+to\s+the\s+confirmed-done\s+set", b6_section,
        re.IGNORECASE,
    ), (
        "AGENTS.md's B6 subsection must say a coherent-reply member is NOT "
        "added to the confirmed-done set — kept alive, not confirmed"
    )
    # Added (ticket #68 review round 1, follow-up finding): AGENTS.md
    # counterpart of the "no second ping after a coherent reply" invariant
    # (SKILL.md: "Send no second ping"; AGENTS.md: "no second ping follows
    # a coherent reply"). Already within `_extract_b6_section`'s scope.
    assert re.search(r"no\s+second\s+ping", b6_section, re.IGNORECASE), (
        "AGENTS.md's B6 subsection must explicitly say no second ping is "
        "sent following a coherent reply"
    )


# ---------------------------------------------------------------------------
# Group 21 — ticket #71: explicit `final: true` terminal marker keys the
# confirmed-done set (replaces inferred "report received" correlation)
# ---------------------------------------------------------------------------
#
# Root cause: ticket #69 introduced a confirmed-done set that a member enters
# "the moment its Final-step report is received" — an inferred correlation,
# not a marker the orchestrator can check directly. Because members are known
# to ping idle more than once after reporting, and the entry condition was
# never pinned to an explicit field in the report, repeated post-report idle
# pings risked being re-evaluated rather than cheaply short-circuited.
#
# Fix: process-ticket's Final step 7 report format now carries an explicit
# terminal-marker field, `final: true`, in BOTH `solo` and `integration`
# mode. orchestrate-tickets' Phase C confirmed-done set is re-keyed on the
# PRESENCE of that marker in the received report, and documents that
# repeated/consecutive idle pings from an already-confirmed-done member are
# all idempotent no-ops — zero B6 evaluations, not one per ping. AGENTS.md's
# B6 paragraph and Cross-file consistency invariant are updated to match.
#
# Red -> green: these tests fail against the pre-#71 SKILL.md/AGENTS.md (no
# `final: true` terminal marker anywhere, no "zero B6 evaluation(s)" phrasing)
# and pass once process-ticket's Final step 7, orchestrate-tickets' Phase C,
# its Hard Rules B6 bullet, and AGENTS.md's B6 section all document the
# terminal-marker keying and idempotency guarantee.


def test_phase_c_two_consecutive_idle_pings_from_confirmed_done_member_zero_b6_evals():
    """The required regression test: Phase C must document that two
    consecutive / repeated idle pings from one already-confirmed-done member
    are all no-ops that resolve to zero B6 evaluations in total."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(
        r"(idempotent|consecutive|repeated).{0,200}(idempotent|consecutive|repeated)?",
        phase_c, re.DOTALL | re.IGNORECASE,
    ) and re.search(r"idempotent", phase_c, re.IGNORECASE), (
        "Phase C must explicitly describe the confirmed-done short-circuit "
        "as idempotent for repeated/consecutive idle pings"
    )
    assert re.search(r"zero\s+B6\s+evaluations?", phase_c, re.IGNORECASE), (
        "Phase C must explicitly say repeated idle pings from a "
        "confirmed-done member cost zero B6 evaluations, not one each"
    )


def test_process_ticket_report_carries_terminal_marker_both_modes():
    """process-ticket's Final step 7 report format must carry the literal
    `final: true` terminal-marker field, and the requirement must apply to
    both `solo` and `integration` mode."""
    process_body = _extract_body(_read(PROCESS_MD))
    report_back_m = re.search(
        r"7\.\s+\*\*Report back:\*\*.*?(?=\n## Hard rules)",
        process_body, re.DOTALL,
    )
    assert report_back_m, "process-ticket SKILL.md must contain a '7. **Report back:**' step"
    report_back = report_back_m.group(0)

    # Bind `final: true` to EACH mode's own bullet block, not just somewhere
    # in the whole step-7 section — a report format where the marker was
    # dropped from one mode's bullet (e.g. left only in the explanatory
    # paragraph below both bullets) must fail this test.
    solo_bullet_m = re.search(
        r"-\s+\*\*`solo`\s+mode:\*\*.*?(?=\n\s+-\s+\*\*|\Z)",
        report_back, re.DOTALL,
    )
    integration_bullet_m = re.search(
        r"-\s+\*\*`integration`\s+mode:\*\*.*?(?=\n\s+-\s+\*\*|\Z)",
        report_back, re.DOTALL,
    )
    assert solo_bullet_m, (
        "process-ticket's Final step 7 must have a dedicated `solo` mode "
        "bullet"
    )
    assert integration_bullet_m, (
        "process-ticket's Final step 7 must have a dedicated `integration` "
        "mode bullet"
    )
    assert "final: true" in solo_bullet_m.group(0), (
        "process-ticket's Final step 7 `solo` mode bullet must itself carry "
        "the literal `final: true` terminal-marker field, not just mention "
        "it elsewhere in step 7"
    )
    assert "final: true" in integration_bullet_m.group(0), (
        "process-ticket's Final step 7 `integration` mode bullet must "
        "itself carry the literal `final: true` terminal-marker field, not "
        "just mention it elsewhere in step 7"
    )


def test_phase_c_confirmed_done_keyed_on_terminal_marker():
    """Phase C must re-key confirmed-done set entry on the presence of the
    explicit `final: true` terminal marker, directly tied to the 'enters it'
    set-entry sentence — not an inferred correlation, and not merely a
    marker mention somewhere else in Phase C."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)

    # (b) the marker must appear directly adjacent to the set-entry
    # ("enters it") sentence, not just anywhere in Phase C.
    adjacency_m = re.search(
        r"enters it the moment its report carries[\s\S]{0,80}?final:\s*true",
        phase_c,
    )
    assert adjacency_m, (
        "Phase C's confirmed-done set-entry sentence ('a member enters it "
        "the moment ...') must be directly tied to the explicit `final: "
        "true` terminal marker within that same sentence — a marker "
        "mention elsewhere in Phase C is not sufficient"
    )

    # (a) the old inferred-correlation phrasing (set entry keyed on "a
    # report arrived", with no marker qualifier) must be gone.
    assert not re.search(
        r"enters it the moment its Final-step report is received\b",
        phase_c,
    ), (
        "Phase C must not retain the old inferred-correlation phrasing "
        "('enters it the moment its Final-step report is received') that "
        "keys set entry on report arrival alone, without the explicit "
        "terminal marker"
    )


def test_agents_md_b6_documents_terminal_marker_keying():
    """AGENTS.md's B6 section must mention the `final: true` terminal marker
    and the idempotency guarantee for repeated post-report idle pings."""
    text = _read(AGENTS_MD)
    b6_section = _extract_b6_section(text)
    assert re.search(r"final:\s*true", b6_section) or re.search(
        r"terminal\s+marker", b6_section, re.IGNORECASE
    ), (
        "AGENTS.md's B6 section must mention the `final: true` terminal "
        "marker"
    )
    assert re.search(r"idempotent", b6_section, re.IGNORECASE), (
        "AGENTS.md's B6 section must document the idempotency guarantee for "
        "repeated post-report idle pings"
    )
