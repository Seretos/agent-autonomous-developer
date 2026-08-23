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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _extract_teardown(body: str) -> str:
    m = re.search(r"## Teardown.*?(?=\n## Hard rules)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Teardown' section"
    return m.group(0)


def _extract_phase_c_step5(body: str) -> str:
    m = re.search(
        r"5\. \*\*Integration gate.*?(?=\n## Phase D)", body, re.DOTALL
    )
    assert m, "SKILL.md must contain Phase C step 5 (integration gate)"
    return m.group(0)


def _extract_sh_fence(text: str) -> str:
    m = re.search(r"```sh\s*\n(.*?)```", text, re.DOTALL)
    assert m, "Teardown must contain a fenced ```sh``` block for the POSIX recipe"
    return m.group(1)


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
    """Updated for ticket #86: the POSIX snippet replaced the old unfiltered
    `pkill -f` sweep with a pgrep-filtered B2-match recipe (see
    test_orchestrate_probe_self_match.py for the full self/ancestor/
    descendant-exclusion and /proc-cwd-refinement coverage). This asserts
    the new POSIX form is present, deliberately in place of the retired
    `pkill -f` literal. Scoped to the Teardown section specifically (ticket
    #86 round-7 finding F2) rather than the whole file, so this test can
    only pass if the snippets genuinely live in the Teardown recipe, not
    merely somewhere else in SKILL.md."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    td = _extract_teardown(body)
    assert "Get-CimInstance Win32_Process" in td, (
        "SKILL.md's Teardown section must keep the Windows "
        "Get-CimInstance Win32_Process snippet"
    )
    sh_block = _extract_sh_fence(td)
    assert "pgrep -f" in sh_block, (
        "SKILL.md's Teardown section must keep the POSIX pgrep -f snippet in "
        "the fenced ```sh``` recipe block specifically, not merely somewhere "
        "in the Teardown section's explanatory prose"
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
# Group 14 — ticket #88: sequential/unnamed wave-member dispatch replaces
# the former B6 report-loss fallback
# ---------------------------------------------------------------------------
#
# Root cause: tickets #64/#68/#69/#71/#83/#86 built up an elaborate
# self-healing apparatus (git-state + result-marker verification, a
# status-check SendMessage ping, bounded liveness probes, wedged-process
# detection) to COMPENSATE for wave members necessarily being
# background/named `Agent` spawns (the only mechanism that runs
# concurrently) whose report-back could silently drop. A live incident
# (ticket #88) found that apparatus was compensating for an avoidable
# problem: driving members in parallel is what forced the background/named
# spawn in the first place, and produced repeated silent report loss in one
# run (duplicate developer instances racing in the same worktree, a report
# arriving at the wrong parent, a developer skipping its mandated test run).
#
# Fix: Phase C now drives wave members SEQUENTIALLY, one fresh synchronous
# unnamed spawn at a time — eliminating the precondition for report loss
# rather than adding another detection layer. The entire B6 apparatus
# (git-state fallback, result-marker reading for merge decisions,
# status-check ping, liveness probes, confirmed-done set, "wedged" verdict)
# is removed from both SKILL.md and AGENTS.md, not merely narrowed.
#
# Red -> green: BR1's tests fail against the pre-#88 SKILL.md (which
# explicitly says "Drive `process-ticket` per member, in parallel" and
# documents named/background spawns) and pass once Phase C documents
# sequential, unnamed dispatch instead. BR2's tests fail against the
# pre-#88 SKILL.md/AGENTS.md (which carry the full B6 apparatus, complete
# with the literal phrases "status-check ping", "confirmed-done", "wedged")
# and pass once that apparatus is gone from both files.


def _extract_phase_c(body: str) -> str:
    phase_c_m = re.search(r"## Phase C.*?(?=\n## Phase D)", body, re.DOTALL)
    assert phase_c_m, "SKILL.md must contain a '## Phase C' section"
    return phase_c_m.group(0)


# ---------------------------------------------------------------------------
# BR1 — Phase C dispatches wave members sequentially, one fresh
# synchronous unnamed spawn at a time, never parallel/named spawns
# ---------------------------------------------------------------------------


def test_phase_c_dispatches_wave_members_sequentially_unnamed():
    """BR1 driving test: Phase C step 2 must document sequential, unnamed
    process-ticket dispatch, not parallel/named spawns."""
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert not re.search(
        r"Drive\s+`process-ticket`\s+per\s+member,\s+in\s+parallel", phase_c,
        re.IGNORECASE,
    ), (
        "Phase C step 2 must no longer say wave members are driven 'in "
        "parallel' — ticket #88 made this sequential"
    )
    assert re.search(r"SEQUENTIALLY", phase_c), (
        "Phase C step 2 must document driving process-ticket per member "
        "SEQUENTIALLY"
    )
    assert re.search(r"one\s+at\s+a\s+time", phase_c, re.IGNORECASE), (
        "Phase C step 2 must say members are dispatched one at a time"
    )
    assert re.search(r"fresh,?\s+synchronous,?\s+unnamed", phase_c, re.IGNORECASE), (
        "Phase C step 2 must describe each member's dispatch as a fresh, "
        "synchronous, unnamed spawn"
    )


def test_phase_c_no_longer_describes_members_as_necessarily_background_named():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert not re.search(
        r"necessarily\s+means\s+each\s+is\s+a\s*\n?\s*background/named",
        phase_c, re.IGNORECASE,
    ), (
        "Phase C must no longer claim wave members are necessarily "
        "background/named spawns — sequential dispatch means they aren't"
    )


def test_hard_rules_no_longer_claim_process_ticket_dispatch_is_parallel():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    hard_rules_m = re.search(r"## Hard rules.*", body, re.DOTALL)
    assert hard_rules_m, "SKILL.md must contain a '## Hard rules' section"
    hard_rules = hard_rules_m.group(0)
    assert "Driving `process-ticket` for each wave member IS parallel" not in hard_rules, (
        "Hard Rules must no longer claim driving process-ticket per wave "
        "member IS parallel — ticket #88 made this sequential"
    )
    assert re.search(
        r"process-ticket.{0,120}sequential|sequential.{0,120}process-ticket",
        hard_rules, re.IGNORECASE | re.DOTALL,
    ), (
        "Hard Rules must document that process-ticket dispatch is now "
        "sequential"
    )


def test_root_cause_note_references_ticket_88():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    phase_c = _extract_phase_c(body)
    assert re.search(r"#88", phase_c), (
        "Phase C must reference ticket #88 as the fix that eliminated "
        "background/named wave-member spawns"
    )


# ---------------------------------------------------------------------------
# BR2 — the B6 self-healing apparatus is removed, not narrowed, from both
# SKILL.md and AGENTS.md
# ---------------------------------------------------------------------------


def test_orchestrate_skill_no_longer_documents_b6_apparatus():
    text = _read(ORCHESTRATE_MD)
    body = _extract_body(text)
    for phrase in (
        "status-check ping",
        "confirmed-done set",
        "Conservative non-merge rule",
        "alive-and-progressing",
        "wedged",
        "idle-triggered",
        "idle_notification",
    ):
        assert phrase.lower() not in body.lower(), (
            f"skills/orchestrate-tickets/SKILL.md must no longer contain "
            f"the B6-specific phrase {phrase!r} — ticket #88 removed the "
            "self-healing apparatus, not just narrowed it"
        )


def test_agents_md_no_longer_documents_b6_apparatus():
    text = _read(AGENTS_MD)
    for phrase in (
        "status-check ping",
        "confirmed-done set",
        "Conservative non-merge rule",
        "alive-and-progressing",
    ):
        assert phrase.lower() not in text.lower(), (
            f"AGENTS.md must no longer contain the B6-specific phrase "
            f"{phrase!r} — ticket #88 removed the self-healing apparatus, "
            "not just narrowed it"
        )


def test_agents_md_documents_sequential_dispatch_replaces_b6():
    text = _read(AGENTS_MD)
    assert re.search(r"#88", text), (
        "AGENTS.md must reference ticket #88's fix"
    )
    assert re.search(r"sequential", text, re.IGNORECASE), (
        "AGENTS.md must document the sequential wave-member dispatch that "
        "replaced the former B6 safeguard"
    )
    assert re.search(r"unnamed", text, re.IGNORECASE), (
        "AGENTS.md must document that wave members are now unnamed spawns"
    )


# ---------------------------------------------------------------------------
# Group 15 — ticket #64, unaffected by #88: target-repo .gitignore fix (the
# marker file is still written unconditionally by process-ticket, regardless
# of whether anything in orchestrate-tickets still reads it)
# ---------------------------------------------------------------------------




def test_agents_md_documents_target_repo_gitignore_fix():
    text = _read(AGENTS_MD)
    assert re.search(r"target repo'?s own\*{0,4}\s*`?\.gitignore`?", text, re.IGNORECASE), (
        "AGENTS.md must document that the real gitignore fix targets the "
        "TARGET repo's own .gitignore, not this plugin's own .gitignore"
    )


# ---------------------------------------------------------------------------
# Group 16 — ticket #71, unaffected by #88: process-ticket's Final step 7
# report format still carries the `final: true` terminal marker in both
# modes (process-ticket writes it unconditionally regardless of whether
# orchestrate-tickets reads it)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Group 17 — reviewer fix round on ticket #88: process-ticket's Final step 6
# and 7 must no longer describe the removed B6 apparatus as still active.
# ---------------------------------------------------------------------------
#
# Root cause (review finding): Final step 6/7's prose still said the
# result-marker file exists so a caller can recover state "e.g. a parallel
# `orchestrate-tickets` wave-member spawn that goes idle without replying --
# see AGENTS.md's B6 note and skills/orchestrate-tickets/SKILL.md's Phase C
# fallback, which reads this exact file" and that a caller "keys its
# confirmed-done-set entry on (see AGENTS.md's B6 note)". Both claims are
# false post-#88: Phase C no longer dispatches in parallel, no longer reads
# .process-ticket-result.json at all, and there is no confirmed-done-set any
# more. The marker file itself is still written unconditionally, every run,
# as a harmless diagnostic artifact -- only the claim that something reads it
# is what must be removed.
#
# Red -> green: these tests fail against the pre-fix SKILL.md (Final step
# 6/7 still describe the removed B6 mechanism as active) and pass once that
# prose is rewritten to match AGENTS.md's own post-#88 framing.


def _extract_final_step(body: str) -> str:
    m = re.search(r"## Final step.*?(?=\n## Hard rules)", body, re.DOTALL)
    assert m, "process-ticket SKILL.md must contain a '## Final step' section"
    return m.group(0)


def test_final_step_no_longer_claims_parallel_wave_member_spawn():
    """Final step must not describe a wave-member spawn as parallel --
    ticket #88 made orchestrate-tickets' wave-member dispatch sequential."""
    process_body = _extract_body(_read(PROCESS_MD))
    final_step = _extract_final_step(process_body)
    assert not re.search(r"\bparallel\b", final_step, re.IGNORECASE), (
        "process-ticket SKILL.md's Final step must not contain the word "
        "'parallel' -- ticket #88 made orchestrate-tickets' wave-member "
        "dispatch sequential, so a 'parallel orchestrate-tickets wave-member "
        "spawn' is no longer a real scenario"
    )


def test_final_step_no_longer_claims_phase_c_reads_the_marker_file():
    """Final step must not claim orchestrate-tickets' Phase C fallback reads
    the result-marker file -- that fallback was removed by ticket #88."""
    process_body = _extract_body(_read(PROCESS_MD))
    final_step = _extract_final_step(process_body)
    assert not re.search(r"reads\s+this\s+exact\s+file", final_step, re.IGNORECASE), (
        "process-ticket SKILL.md's Final step must not claim "
        "orchestrate-tickets' Phase C fallback 'reads this exact file' -- "
        "ticket #88 removed that fallback entirely; nothing in "
        "orchestrate-tickets reads the marker file any more"
    )
    assert "orchestrate-tickets" not in final_step or not re.search(
        r"Phase\s+C\s+fallback", final_step, re.IGNORECASE
    ), (
        "process-ticket SKILL.md's Final step must not reference an "
        "orchestrate-tickets 'Phase C fallback' -- ticket #88 removed it"
    )


def test_final_step_no_longer_claims_confirmed_done_set():
    """Final step must not reference a confirmed-done-set -- ticket #88
    removed the concept along with the rest of the B6 apparatus."""
    process_body = _extract_body(_read(PROCESS_MD))
    final_step = _extract_final_step(process_body)
    assert "confirmed-done" not in final_step.lower(), (
        "process-ticket SKILL.md's Final step must not reference a "
        "confirmed-done set -- ticket #88 removed the B6 apparatus that used "
        "one, and orchestrate-tickets no longer tracks one"
    )


def test_final_step_no_longer_names_b6_by_label():
    """Final step must not reference the retired 'B6' safeguard by name --
    it should instead reference ticket #88's own framing of the change."""
    process_body = _extract_body(_read(PROCESS_MD))
    final_step = _extract_final_step(process_body)
    assert not re.search(r"\bB6\b", final_step), (
        "process-ticket SKILL.md's Final step must no longer name the "
        "retired 'B6' safeguard -- reference ticket #88 instead, matching "
        "AGENTS.md's own post-#88 framing"
    )
    assert re.search(r"#88", final_step), (
        "process-ticket SKILL.md's Final step should still reference ticket "
        "#88 when explaining why the marker file's readers changed"
    )


def test_final_step_marker_still_written_unconditionally_as_diagnostic():
    """The marker file's write itself is unaffected by #88 -- it must still
    be described as unconditional, every run, now framed as a harmless
    diagnostic artifact rather than a report-loss fallback input."""
    process_body = _extract_body(_read(PROCESS_MD))
    final_step = _extract_final_step(process_body)
    step6_m = re.search(
        r"6\.\s+\*\*Write a result-marker file.*?(?=\n7\.\s+\*\*Report back)",
        final_step, re.DOTALL,
    )
    assert step6_m, "Final step must contain step 6 ('Write a result-marker file')"
    step6 = step6_m.group(0)
    assert re.search(r"unconditional", step6, re.IGNORECASE), (
        "Final step 6 must still say the marker write is unconditional"
    )
    assert re.search(r"diagnostic", step6, re.IGNORECASE), (
        "Final step 6 must now frame the marker as a harmless diagnostic "
        "artifact, since nothing reads it as a report-loss fallback input "
        "any more"
    )


# ---------------------------------------------------------------------------
# Group 18 — reviewer fix round on ticket #88 (round 2, finding 5): step 7's
# `final: true` paragraph must not claim orchestrate-tickets' Phase C reads
# that field. orchestrate-tickets/SKILL.md never mentions or reads
# `final: true` anywhere -- its documented merge criterion only checks
# `VERDICT: APPROVE` and test `PASS`/`FAIL`. `final: true` is simply unread
# by anything now, same as the marker file itself.
# ---------------------------------------------------------------------------


def test_final_true_paragraph_does_not_claim_phase_c_reads_it():
    process_body = _extract_body(_read(PROCESS_MD))
    final_step = _extract_final_step(process_body)

    assert not re.search(
        r"reads\s+this\s+field\s+straight\s+off", final_step, re.IGNORECASE
    ), (
        "process-ticket SKILL.md's Final step 7 `final: true` paragraph "
        "must not claim orchestrate-tickets' Phase C 'reads this field "
        "straight off' the process-ticket report -- Phase C never reads "
        "`final: true` at all"
    )


def test_orchestrate_md_never_mentions_final_true():
    """Cross-file check backing the finding: orchestrate-tickets/SKILL.md
    must not mention `final: true` anywhere -- it is not part of Phase C's
    merge criterion (VERDICT: APPROVE + test PASS/FAIL only)."""
    orchestrate_body = _extract_body(_read(ORCHESTRATE_MD))
    assert "final: true" not in orchestrate_body, (
        "orchestrate-tickets/SKILL.md must not mention 'final: true' -- "
        "nothing in Phase C reads that field"
    )


# ---------------------------------------------------------------------------
# Group 19 (ticket #88, reviewer fix round 2, finding 6) — recovered from the
# wholesale-deleted tests/test_orchestrate_liveness_check.py. That file was
# deleted in round 1 of this ticket's fix loop because most of its coverage
# was specific to the removed B6 apparatus, but it also carried coverage for
# invariants ticket #88 did NOT remove: Phase C step 5's (the integration
# gate, still live/unchanged) documented nohup+Monitor backgrounded pattern,
# and the B1 push-before-next-wave / RED-no-auto-revert ordering scoped
# specifically to that step. These two are recovered here, adapted to no
# longer reference the removed B6 mechanism. (Group 7/8/9 above already give
# body-wide coverage of the full-suite/B1/RED substance; these add scoped,
# step-5-specific coverage matching the original test's precision, so a
# future edit that moves this substance out of step 5 specifically -- while
# leaving stray mentions elsewhere in the file -- is still caught.)
# ---------------------------------------------------------------------------


def test_phase_c_step5_documents_nohup_monitor_backgrounded_pattern():
    body = _read(ORCHESTRATE_MD)
    step5 = _normalize(_extract_phase_c_step5(_extract_body(body)))

    assert "nohup" in step5 and "Monitor" in step5, (
        "Phase C step 5's integration gate must document the backgrounded "
        "nohup + Monitor pattern"
    )
    assert "Set-Location <repo_root>" in step5 or "cd <repo_root>" in step5, (
        "Phase C step 5 must keep its Set-Location/cd <repo_root> first "
        "statement, since the test runner is the one non-git, "
        "cwd-dependent step in this skill"
    )
    assert re.search(r"~?10-minute", step5, re.IGNORECASE), (
        "Phase C step 5 must explain the backgrounded form via the "
        "~10-minute foreground tool-timeout it avoids"
    )


def test_phase_c_step5_b1_push_and_red_no_auto_revert_ordering():
    body = _read(ORCHESTRATE_MD)
    step5 = _normalize(_extract_phase_c_step5(_extract_body(body)))

    assert "push origin" in step5 and "before the next wave".lower() in step5.lower(), (
        "Phase C step 5 must document pushing the integration branch as a "
        "hard precondition (B1) before the next wave creates any worktree"
    )
    assert re.search(r"no automatic revert|no auto[- ]revert", step5, re.IGNORECASE), (
        "Phase C step 5 must document that a RED integration gate STOPs "
        "with no automatic revert"
    )
    # Ordering: the GREEN (push-before-next-wave) branch must be documented
    # before the RED (no-auto-revert) branch, matching the original
    # narrative order.
    green_idx = step5.lower().index("on green")
    red_idx = step5.lower().index("on red")
    assert green_idx < red_idx, (
        "Phase C step 5 must document the GREEN branch before the RED "
        "branch"
    )
