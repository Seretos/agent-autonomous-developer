---
name: orchestrate-tickets
disable-model-invocation: true
description: Required entry-point for executing ticket work — one ticket, several, or all open — for a project (stack auto-detected). Use to split tickets, re-slice epics, and execute them. Serial/single-ticket is the normal safe path (SINGLE mode); parallel fleet drives per-wave process-ticket(mode=integration) runs to a shared integration branch, merges and gates each wave, and opens exactly one combined draft PR at the end. Bypassing it — manual work on `main`, or editing inside a worktree directly — forfeits code review, planner approval, QA/tests, Codex pass, and PR-based merge.
---

# orchestrate-tickets — fleet orchestrator

You drive ticket work across parallel, isolated worktrees end-to-end, wave by
wave, to one combined PR. You decide *what* runs (via the `conflict-analyst`
subagent, laying tickets out into ordered waves), create each wave's
worktrees, and then drive `process-ticket` yourself for every wave member in
`mode=integration` (context → plan → code → review). You implement nothing —
`process-ticket` still owns the actual editing — but you no longer stop after
worktree creation: you merge each wave's approved-and-green members into a
shared integration branch, gate the merge with a full-suite run, push on
green, and repeat for the next wave. At the end of the run you open the
**single combined draft PR** yourself — the user is not required to drive any
worktree session manually. See Phase C (the wave loop) and Phase D (the
single combined PR) below for the full mechanics.

There is **no cwd→project auto-detection**. The `project_id` is supplied at
invocation (see Inputs); pass it to the analyst and to every project-issues call.

**Scope note — bare ticket creation is not this skill's job.** To merely file a
new ticket, call `create_ticket` directly (the project-issues MCP). This skill is
for *executing* ticket work — and for splitting or re-slicing tickets when
decomposing that work before execution. Routing a simple "file a ticket" request
through this skill adds unnecessary overhead (worktree creation, fleet
orchestration).

### Single-ticket / serial path (the normal, always-correct path)

A single non-parallelizable or foundational ticket does **not** need a fleet.
SINGLE mode (one ticket given) is the **default safe path**: it skips the
conflict-analyst entirely and creates one worktree.
"Not running in the parallel fleet" does **not** mean "do it manually on
`main`" — it means run SINGLE mode through this skill.

Working a ticket manually (editing files on `main`, committing directly, or
force-pushing) bypasses every safety gate the workflow enforces: planner
approval, developer QA/tests, reviewer subagent + Codex correctness pass,
PR-based merge, and the no-force-push rule on shared branches. **This is not
permitted.** Every ticket — serial or parallel, foundational or incremental,
one or many — goes through this skill.

**Verify vs. edit.** Building or running the project locally from the main checkout to *verify* behaviour — without touching source files — is acceptable from the main checkout. Any *edit* (changing source files, config, or tests in response to a request like "fix the CI pipeline" or "build & start locally") is ticket work and must be routed through this skill — even as a SINGLE-mode ticket — so it receives planner approval, developer QA/tests, reviewer + Codex pass, and PR-based merge. The orchestrator session must not make edits inside a worktree directly, even one it created; that is the worker's territory.

## How to slice when authoring tickets

These rules apply **whenever you are creating, splitting, or re-slicing tickets**
— regardless of whether the conflict-analyst later runs. They are not gated on
MULTI mode.

- **1 ticket = 1 vertical full-stack slice = 1 worktree = 1 PR.** Each ticket
  must own a thin but complete feature path: data model → business logic →
  API → UI → tests, all in one ticket. One ticket, one PR.
- **Target 2–6 tickets for a body of work.** If the work is large, decompose it
  into a serial sequence of vertical wave-tickets (wave 1 lands, wave 2 branches
  off it). Never decompose by adding more parallel tickets beyond what can run
  safely concurrently.
- **Forbidden — horizontal/layer cuts.** Never create separate tickets for
  "DB layer", "API layer", "UI layer", or similarly named seam/impl/wire tickets
  that cover the same feature. All three layers must land before the feature is
  observable, so the parallelism buys nothing and each worker implements an
  incomplete slice.
- **Forbidden — splitting for parallelism.** Never split a ticket purely to gain
  parallelism. Split only when the resulting tickets are each independently
  shippable vertical slices.
- **Forbidden — tickets that aren't independently shippable.** If a ticket
  delivers no observable value on its own (nothing to review, test, or demo), it
  is a layer cut in disguise — merge it into its vertical slice.

## Fit-awareness — when this workflow is (and isn't) the right tool

This plugin's execution model is **isolated workers with no shared context**: each
ticket gets its own worktree, but tickets merge wave-by-wave into one shared
integration branch and land in exactly **one combined PR** per run, not one
PR per ticket.
That model has fixed overhead per ticket (worktree creation, review) and a
parallelism ceiling set by how independent the tickets are. It fits some
ticket shapes well and others poorly.

### Good fit signals

- **Few tickets (roughly 2–6)** — the per-ticket startup overhead is justified
  when each ticket delivers meaningful value on its own.
- **Large vertical slices** — each ticket owns a full feature top-to-bottom
  (data model → business logic → API → UI → tests in one ticket). The worker
  can implement and review the whole thing without waiting on another worker.
- **Sparse DAG (`dag_depth` 0–2)** — dependency chains are short; most tickets
  have no predecessors and can start immediately.
- **High parallelism ratio** — most tickets land in the `parallel` set; few or
  none are deferred, so the fixed per-ticket overhead is spread across real
  concurrent work.

### Poor fit signals

- **Deep dependency chains (`dag_depth > 2`)** — a long chain forces sequential
  waves and narrows the achievable wave width; most tickets end up deferred,
  not parallel.
- **Many tickets touching the same shared integration file(s) across different
  dependency waves** — even when files don't conflict within a wave, the same
  file appearing in multiple waves signals a "moving base" reconvergence problem:
  later waves must absorb changes from earlier ones, a surface the conflict
  analyst's static footprint check cannot fully prevent.
- **Horizontally/layer-cut tickets** — e.g. "DB layer", "API layer", "UI layer"
  as separate tickets for the same feature. All three must land before the
  feature is observable, so the parallelism buys nothing and each worker
  implements an incomplete slice. Vertical slicing (each ticket owns a thin
  full-stack slice of the feature) fits the isolated model; horizontal slicing
  does not.
- **High ticket count with low parallelism** — when most tickets end up
  deferred, the fixed per-ticket overhead (worktree creation, review) dominates
  over the parallelism actually gained. This is not PR overhead — there is
  exactly one PR per run, not per ticket — but worktree creation and review
  still scale with ticket count.
- **`min_wave_width == 1`** — at least one wave is a serial bottleneck: only
  one ticket can run in that wave. A narrow bottleneck wave stalls all
  downstream work.

### The isolation model contrast

This plugin's isolated-worker model is well-suited to **independent, vertically-
sliced work**. A future `autonomous-teams` shared-context model — where workers
share working memory — would tolerate horizontal slicing because context crosses
worker boundaries. Slicing knowledge belongs in `orchestrate-tickets` and the
`conflict-analyst`, not in a standalone `slice-tickets` skill, because a re-slicing
recommendation is only meaningful relative to the execution model it describes.
Splitting it out would decouple recommendation from model, making both stale on
future changes.

### Fit assessment applies only in MULTI mode

The slicing rules in `## How to slice when authoring tickets` are **unconditional**
— they apply at authoring time regardless of mode. What is gated to MULTI mode is
the **diagnostic output**: the `fit` field and the Phase B Fit Warning below are
only produced when the conflict-analyst runs (MULTI mode). SINGLE mode does not
invoke the conflict-analyst and produces no fit evaluation.

## Inputs

- A **project id** (e.g. `acme-api`). If missing or unclear, resolve it via
  `find_projects` and confirm with the user before doing anything.
  - **Reject placeholder project ids.** `find_projects` can return a generic
    id via the `source: "git-remote"` auto-discovery path (e.g. `_auto`).
    Before using the resolved id anywhere, check it against the blocklist:
    strip any leading `_`, then compare case-insensitively against `auto`,
    `default`, and `session`. If it matches, derive a slug from the last path
    segment of the `path` or `web_url` field returned by `find_projects`
    (e.g. `path: "Seretos/obsidian-memory-gatekeeper"` → slug
    `obsidian-memory-gatekeeper`). If no unambiguous non-placeholder slug can
    be derived this way (both fields absent or empty), confirm with the user —
    consistent with the "confirm with the user" rule above.

    *Worked example:* `find_projects` returns `source: "git-remote"`,
    `project_id: "_auto"`, `path: "Seretos/obsidian-memory-gatekeeper"`.
    Strip leading `_` → `auto` → matches the blocklist. Derive slug from last
    segment of `path` → `obsidian-memory-gatekeeper`. Use
    `obsidian-memory-gatekeeper` as the project id from this point forward.

    *Edge cases:* `_auto` (strip underscore → matches); `auto` (direct match);
    `default`, `session` (both in blocklist); `automate-api` (does **not**
    match — full-token equality, not substring); `path` and `web_url` both
    absent → fall through to "confirm with the user"; non-placeholder id
    (e.g. `acme-api`) passes silently.

    This check occurs on the value returned by `find_projects`.
- An optional ticket number, or several, or nothing.
  - **exactly one** ticket → SINGLE mode (skip analysis).
  - **none** → MULTI mode over **all open** tickets.
  - **several** → MULTI mode over **that subset**.

## Preconditions

0. **Run only from the main checkout — never inside a worktree.** This skill is
   the mirror of `process-ticket` (which runs only *inside* a worktree on a
   feature branch). Guard before doing anything else:
   - `git rev-parse --abbrev-ref HEAD` must be the repo's default branch.
   - `git rev-parse --git-dir` must EQUAL `git rev-parse --git-common-dir`
     (they differ when you are inside a linked worktree).
   If either check fails, **STOP** and tell the user to run orchestrate-tickets
   from the project's main checkout — otherwise the worktrees it spawns and the
   orchestrator's own branch/state collide with the workers.
1. **Capture repo + base branch.** `git rev-parse --show-toplevel` → `repo_root`.
   Determine the repo's default branch → `base`. `base` is only the starting
   point for the run's integration branch (step 3) — worktrees branch off the
   **integration branch's current head**, not `base` directly (see Phase C).
2. **Refresh `base` from the remote — guard against stale worktrees.** Before
   creating any worktree, bring the main checkout's default branch up to date so
   the integration branch doesn't start from a stale `base`: `git fetch origin`
   then `git pull --ff-only` (you are on the default branch per Precondition 0).
   If it can't fast-forward (the local branch has diverged) or a dirty working
   tree blocks it, **STOP** and tell the user to reconcile the main checkout
   first — never merge, rebase, or force. Stopgap: `worktree_create` does
   **not** refresh from the remote itself yet, so the skill must do it here.
3. **Create the shared integration branch.** After the refresh above, create a
   run-scoped integration branch off the freshly-pulled `base`:
   `git branch <integration> <base>` where `<integration>` is
   `integration/<run-slug>` (`<run-slug>` — a short, unique identifier for this
   run, e.g. a date-stamp plus the lead ticket number, such as
   `integration/2026-07-13-171`). Push it once right away:
   `git push -u origin <integration>`. Capture `<integration>` — every wave's
   worktrees, merges, and the final combined PR all key off this one branch for
   the rest of the run.
4. **Worktree mechanism — agent-worktree MCP only.** Worktree creation uses the
   **agent-worktree MCP** (`worktree_create`). If that MCP is **not loaded** in
   this session (fresh sessions don't auto-load plugin MCPs), **STOP** and tell
   the user to `/reload-plugins` (or do a one-time `--scope user` install of the
   plugin), then re-invoke. **Do not** fall back to raw `git worktree add` — that
   produces worktrees the MCP can't track, list, remove, or reconcile (and on
   Windows leaves locked/ports-leaked state on teardown). Confirm the MCP is
   available before Phase B.

## Phase A — decide the target tickets, laid out into waves

**SINGLE mode** (one ticket `#n`): do **not** spawn the analyst. Fetch only the
title for the branch slug — `get_ticket(project_id, n, include_comments=False,
include_relations=False)` — and form `branch = fix/<n>-<slug>` (title
lower-cased, non-alphanumerics → hyphens, ~4 words). **SINGLE mode still
synthesizes one wave** — `waves = [[{ticket: n, branch}]]`, a single-member
wave 0 — so it flows through the exact same wave-based pipeline as MULTI mode
(one iteration of Phase C, one integration-gate run, one final PR), just with
nothing to parallelize.

**MULTI mode** (none, or several): spawn the analyst —
`Agent(subagent_type="conflict-analyst", prompt=…)` — passing `project_id` and
either "all open" or the explicit subset. It returns a readable summary and a
trailing fenced ```json block with `waves` and `deferred` arrays. Parse the
**json block only**; the target set is the ordered `waves` array — a list of
parallel-safe sets (`waves[0]`, `waves[1]`, …), each element keeping the
`ticket`/`branch`/`title`/`files`/`scope` shape. Each `deferred` entry carries
a **`type`**: `"file-collision"` (footprint overlap) or `"logical-dependency"`
(disjoint files, but the ticket states it must come *after* an unmet predecessor —
e.g. a doc/integration ticket). Keep that `type` through to the confirm step
(Phase B) — the two kinds mean different things to the human.

## Phase B — confirm the fleet

1. **Confirm before launching.** Present the planned fleet to the user via
   **AskUserQuestion**: the waves in order (each wave's tickets, with branch +
   footprint), and the deferred ones **grouped by `type`** — `file-collision`
   (would conflict in a shared file) vs `logical-dependency` (clean footprint but
   must wait on an unmet predecessor, with which tickets in its `depends_on`).
   Surfacing the `logical-dependency` group explicitly is the point: each wave
   is conflict-free **and** dependency-respecting, so the human sees that
   ordering was checked, not silently skipped. If the analyst returned **no**
   deferrals at all, state plainly that logical-ordering dependencies were
   checked and none applied — so the blind spot never stays silent.

   **Fit Warning (MULTI mode only, when `fit.verdict == "poor"`):** After
   presenting the waves and deferred groups — and before the go-ahead question
   — display a **Fit Warning** block. Include:
   - The specific signals that triggered `"poor"`, drawn directly from the
     analyst's `fit` field:
     - `dag_depth` value, if `dag_depth > 2`
     - `min_wave_width`, if `min_wave_width == 1`
     - The `cross_wave_shared_files` list, if non-empty
     - The parallelism ratio (`parallel_count / ticket_count`), if below 0.5
   - The analyst's `recommendation` string, verbatim.
   - A plain statement that the orchestrator recommends re-slicing but the human
     decides — the go-ahead prompt is unchanged; the human can proceed as-is.

   When `fit.verdict == "good"`, or in SINGLE mode (no `fit` field), show no
   fit block — proceed directly to the go-ahead question.

   Launching N worktrees across M waves is hard to undo, so get a go-ahead (or
   let the user drop/keep tickets) first. For SINGLE mode keep it light, but
   still confirm the one launch.

## Phase C — the wave loop

Iterate the `waves` array **wave-by-wave, in order**. For each wave:

1. **Create that wave's worktrees, SEQUENTIALLY.** Never in parallel —
   concurrent `git worktree` ops on one repo race on the index lock. Before
   creating any worktree, capture this wave's **branch point**: `git -C
   <repo_root> rev-parse <integration>`, the integration branch's current head
   SHA (call it `<branch_point_sha>`) — every member's worktree in this wave
   branches from exactly this commit, and step 2's fallback protocol needs it
   to prove a member produced a genuine new commit this run, not merely
   inherited the branch-point commit.
   `worktree_create(repo_root, branch=<branch>, base=<integration>)` — branch
   off the **current integration-branch head**, not `base` directly, so each
   wave builds on top of everything already merged from earlier waves. Capture
   the returned `path` for each — **use that returned path**, never construct a
   directory from the branch name (the `fix/<n>-…` convention contains a `/`).
2. **Drive `process-ticket` per member, in parallel.** For every ticket in the
   wave, invoke `process-ticket` with `mode=integration` and
   `worktree_path=<path>` (the path captured above). Each member runs the full
   Phase 1-4 pipeline (context → plan → code → review) and does its own local
   commit, but does **not** push, open a PR, or comment — this skill owns that,
   once, at the end of the whole run (Phase D). Collect each member's ending
   state: `APPROVE`/`CHANGES_REQUESTED` verdict and test PASS/FAIL.

   **Root cause — why a member's report-back can silently never arrive.**
   Driving several members **in parallel** necessarily means each is a
   background/named `Agent` spawn (that's the only mechanism that runs
   concurrently). This is the same delivery mechanism whose failure mode
   caused the planner-spawn deadlock fixed in **#58/#60** (a named spawn
   switches into background/mailbox delivery, and the callee has no
   `SendMessage` tool to push a reply back if that delivery silently drops)
   — see `skills/process-ticket/SKILL.md`'s Phase 2 note for the original
   case. Here it surfaces one level up: a wave member can finish all its real
   work — local commit made, reviewer verdict `APPROVE` — and still go idle
   without ever sending its mandated Final-step report, making an otherwise-
   successful run look stalled. Unlike the planner fix, members here must run
   in parallel, so eliminating background/named spawns is not viable — the
   fix is a fallback, not elimination (this is **AGENTS.md's B6** safeguard).

   **Idle-triggered, timer-free fallback protocol.** The orchestrator has no
   timer and must not wait on one. The trigger is a member going **idle**
   (`idle_notification`/`idleReason: "available"`) **without** having sent its
   Final-step report — a member that reports first and *then* goes idle does
   **not** re-trigger this fallback; the trigger is scoped to idle-**without**-
   a-report, not idle alone. When that happens, do not rely solely on the
   member's self-report — verify its real ending state directly:
   - Run `git -C <worktree_path> log -1` and
     `git -C <worktree_path> status --porcelain`. Expect the marker file
     (see below) to be **absent** from plain `status --porcelain` output on a
     fully successful run — `process-ticket`'s Final step 1 ensures the
     target repo's `.gitignore` contains the marker's line **before** the
     commit, so by the time the marker is written it is already gitignored,
     and a gitignored untracked file produces no entry at all (not even an
     untracked-file marker) in plain `status --porcelain`. This absence is
     expected and is **not** itself a sign of uncommitted work — do not treat
     it as anomalous.
   - Confirm HEAD is actually **ahead of** this wave's branch point (the
     `<branch_point_sha>` captured in step 1 above, the integration-branch
     head this worktree was created from): `git -C <worktree_path> rev-list
     --count <branch_point_sha>..HEAD` must be **> 0**. This check is
     required, not optional — a worktree that never did any real work still
     has a valid `git log -1` (the branch-point commit itself) and can show a
     clean `status --porcelain`, so "a commit exists at HEAD" alone does not
     prove *this run* produced one; combined with a possibly-stale leftover
     marker file, that could otherwise be misread as a confirmed success.
     Only "HEAD is ahead of the branch point" proves a genuine new commit
     landed this run.
   - Only **after** the HEAD-ahead-of-branch-point check above has passed,
     read the result-marker file
     `<worktree_path>/.process-ticket-result.json` (written unconditionally
     by `process-ticket`'s Final step, in both `solo` and `integration` mode
     — see `skills/process-ticket/SKILL.md`) to recover the reviewer
     `verdict` and `test` result — git alone cannot recover those. The marker
     is **not trusted on its own**: since a RED wave deliberately leaves its
     worktrees intact for inspection (no auto-revert), a worktree could in
     principle be reused or retried, and a stale marker from an earlier
     attempt could otherwise be misread as confirming this run. Tying the
     marker's trustworthiness to the already-proven "HEAD is ahead of the
     branch point" fact — a genuine new commit landed this run — is what
     makes reading it safe. Additionally, verify the marker's own `ticket`
     field equals this wave member's actual ticket number; if it does not
     match, the marker is stale (left over from a different ticket ever
     processed in this worktree) and must be **rejected and treated as
     unconfirmed**, exactly as if the marker were missing.

   **Conservative non-merge rule.** A member whose ending state cannot be
   confirmed this way is **not merged**: HEAD not ahead of the branch point
   (no genuine commit this run), the marker file missing or unreadable, the
   marker's `ticket` field not matching this member's actual ticket number
   (stale marker from a different run), the marker's `verdict` is not
   `APPROVE`, **or the marker's `test` is not `PASS`** — any one of these
   disqualifies the member. This matches the ordinary (non-fallback) merge
   criterion in step 4 below — "every member that ended `APPROVE` **with a
   green test run**" — so the fallback path is never weaker than the normal
   path; checking `verdict` alone is not sufficient. A disqualified member
   rolls into a later wave, exactly like today's `CHANGES_REQUESTED`/red
   members; do not merge on the strength of a
   self-report alone.
3. **Checkout the integration branch, then B4 — clean-checkout gate, before
   any merge.** On the main checkout (`repo_root`), first switch onto the
   integration branch itself: `git checkout <integration>` (or
   `git switch <integration>`) — the checkout stayed on `base` since
   Precondition 0/3, and the merges in step 4 below must land on
   `<integration>`, not `base`. Then confirm there is nothing uncommitted
   sitting in the way of the merges about to happen: `git status --porcelain`
   and `git diff` must both be **empty**. If either is non-empty, **STOP** —
   do not merge into a dirty integration-branch checkout.
4. **Merge approved + green members into the integration branch.** For every
   member that ended `APPROVE` with a green test run, merge its branch with
   `git merge --no-ff <branch>` into `<integration>`. Members that were
   `CHANGES_REQUESTED` or reported failing tests are **dropped from this
   merge** — no special handling needed, they simply roll into a later
   (possibly solo, single-member) wave for a subsequent run.
5. **Integration gate — run the full suite on the integration branch**, after
   merging the wave's approved members. This is the cross-wave safety net: it
   catches interactions between this wave's changes and everything merged so
   far, which no single member's own test run could see.
   - **On GREEN:** tear down this wave's worktrees (see Teardown below, with
     the B2/B3 extensions), **then push the integration branch** —
     `git push origin <integration>` is a **hard precondition before the next
     wave creates any worktree (B1)**. Never let a later wave branch off an
     unpushed integration head.
   - **On RED: STOP immediately. There is no automatic revert.** Leave the
     state exactly as it is:
     - The wave's `--no-ff` merge commits remain in the **local** integration
       branch at the failed state, **unpushed** (push only ever happens after
       green, per B1 above) — so a pushed integration branch is never broken.
     - The wave's worktrees are left **intact** — **skip teardown** — so the
       user can inspect them.
     - Already-pushed prior waves **stay pushed** — no rewind, no force-push.
     Report to the user: **which wave failed**, **which member branches got
     merged** into the failed attempt, the **failing test names**, and that
     resolution (fix, drop a member and re-merge, or abandon the run) is the
     user's call, not this skill's.

## Phase D — end of run: one combined draft PR

Once every wave has been processed (all merged-and-pushed, or the run STOPped
per the RED path above and the user has resolved it), close out the run:

1. **Open exactly ONE draft PR** via MCP: `create_pr(project_id=<project>,
   title=<recap>, head=<integration>, base=<default branch>, draft=True,
   body=<run recap listing every merged ticket + "Closes #<n>" for each>)`.
   Never type `#ai-generated` — the MCP prepends it. (`Closes #<n>` auto-links
   on GitHub/GitLab; if the project's provider is Azure DevOps or Jira this
   keyword differs — see AGENTS.md's Provider-portability note, which still
   applies here unchanged.)
2. **Post one link-comment per processed ticket** —
   `add_comment(project_id=<project>, ticket_id=<#>,
   body="Draft PR opened: <PR URL>. <one-line status>")` — for every ticket
   that made it into the integration branch across every wave.
3. **Report to the user:** the PR URL, the full wave-by-wave recap (what
   merged, what was deferred, what — if anything — is still pending
   resolution from a RED gate).
4. **Switch the main checkout back to the default branch.** The main checkout
   has been sitting on `<integration>` since Phase C step 3; now that the
   combined PR is open, `git checkout <base>` (or `git switch <base>`) on the
   main checkout so Precondition 0 holds again for the next invocation of this
   skill.

## Teardown — remove a worktree

When a worktree is no longer needed (its wave's integration gate went green
and it has been merged, or the user asks to tear one down after resolving a
RED gate), remove it **safely and statelessly**:

1. **B2 — kill any process still holding this worktree open.** A
   `process-ticket` run can leave more than one long-lived helper bound to the
   worktree directory: the reviewer's optional Codex pass spawns
   `node … app-server-broker.mjs --cwd <worktree-path> …`, and Serena
   navigation tooling can leave its LSP chain (`node`, `uvx`/`uv`,
   `serena.exe`, `python.exe`) running against the same path. None of these
   are `claude --bg` jobs, so `claude stop` does not reach them, and
   force-killing them triggers **no** daemon respawn. Kill **any process whose
   command-line or cwd references the worktree path** — not just a
   name-matched allowlist — **before** `worktree_remove`, while git still
   knows the worktree, so the MCP's remove stays in sync. On Windows /
   PowerShell (match on the worktree path, generalized beyond a single process
   name):
   ```powershell
   Get-CimInstance Win32_Process |
     Where-Object {
       $_.CommandLine -like '*<worktree-path>*' -and
       ($_.Name -in @('node.exe', 'uvx.exe', 'uv.exe', 'serena.exe', 'python.exe') -or
        $_.CommandLine -like '*app-server-broker.mjs*')
     } |
     ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   ```
   The directory-lock failure is Windows-specific (POSIX lets `git worktree remove`
   unlink a directory with an open handle), but killing orphans is good hygiene
   everywhere — POSIX equivalent, generalized the same way:
   `pkill -f "<worktree-path>"` (broad enough to catch the broker, the Serena
   LSP chain, or any other process rooted in that path). Caveat: this is
   intentionally broad — it kills **any** process whose command line
   references the worktree path, not just the Codex broker/Serena LSP chain,
   so a user-launched editor or shell pointed at that path would also be
   killed.
2. **Confirm the directory is free**, then remove the worktree via the
   agent-worktree MCP (`worktree_remove`) so it releases ports, runs teardown,
   and updates its state store. Do not `rm -rf` the directory or run
   `git worktree remove` by hand — that desyncs the MCP's state.

**Recovery — already-desynced phantom entry.** If a worktree was left desynced
(git no longer lists it, the directory persists, and the MCP still shows
`status: created`), `worktree_remove` — even with `force=true` — fails with
`fatal: '<path>' is not a working tree`. Recover by hand: kill any lingering
process per B2 above → remove the directory
(`Remove-Item -Recurse -Force '<worktree-path>'`) → delete the merged local
branch (`git branch -d <branch>`). The phantom MCP entry then remains —
cosmetic; no agent-worktree MCP call currently prunes it (its own
self-reconcile is tracked in the agent-worktree repo).

**B3 — force-unregister fallback (same branch name reuse).** The recovery
above frees the *directory* and the *local branch*, but the agent-worktree
MCP's own state can still list the phantom entry against that branch name,
which can block creating a **new** worktree under the **same original branch
name** later (e.g. a later wave re-attempting a dropped member on
`fix/9-slug`). If `worktree_create` refuses to reuse the branch name because
the MCP's state still shows the old (already physically-removed) entry as
`created`, **force-unregister without a physical delete**: call
`worktree_remove(..., force=true)` again purely to clear the MCP's bookkeeping
entry (it is a no-op on disk at this point — the directory is already gone)
rather than treating the MCP's stale record as a hard block. This frees the
branch name for reuse without requiring a rename. If the MCP has no
force-unregister-only affordance yet, fall back to picking a disambiguated
branch name (e.g. `fix/9-slug-retry`) for the retry and note the phantom entry
for manual cleanup — never silently fail to retry a dropped member.

## Hard rules

- **Project id is a parameter.** Pass the supplied `project_id` to the analyst
  and every project-issues call — never hardcode a project.
- **Reject placeholder project ids.** Before using the resolved `project_id`
  in any Phase C report, verify it does not match the blocklist: strip any
  leading `_`, then compare case-insensitively against `auto`, `default`, and
  `session`. If it matches, derive a slug from the last path segment of the
  `path` or `web_url` field from the `find_projects` result
  (e.g. `Seretos/obsidian-memory-gatekeeper` → `obsidian-memory-gatekeeper`).
  If no unambiguous slug is available (both fields absent or empty), confirm
  with the user. A non-placeholder id (e.g. `acme-api`) passes silently.
- **Delegate the analysis.** In MULTI mode the `conflict-analyst` decides the
  waves; you never compute footprints yourself. In SINGLE mode you only read the
  title for a slug — no footprint analysis.
- **Parallel-safe = disjoint file footprints AND no unmet logical dependency**
  (the analyst's contract). Tickets that share a source file, *or* that state an
  explicit "must come after #x" dependency on a predecessor not yet done, are
  never placed in the same wave; they go to `deferred` (tagged `file-collision` or
  `logical-dependency`) for a later run. Surface the `logical-dependency` group at
  the confirm step so the ordering check is visible, never silently skipped.
- **agent-worktree MCP only — no raw-git fallback.** If the MCP isn't loaded,
  hard-fail and tell the user to `/reload-plugins`. Never `git worktree add`.
- **Sequential, not parallel**, for worktree creation within a wave (git index
  lock races). Driving `process-ticket` for each wave member IS parallel —
  only the `git worktree` creation step is serialized.
- **Worktrees branch off the integration-branch head, not `base`.** Only the
  integration branch itself (created once, at run start) branches off `base`.
  Every wave's worktrees branch off whatever the integration branch's head is
  at that point in the run, so each wave builds on everything merged before it.
- **B1 — push is a hard precondition before the next wave.** The integration
  branch is pushed only after a wave's integration gate goes GREEN, and that
  push must complete before the next wave creates any worktree. Never let a
  later wave branch off an unpushed integration head.
- **No automatic revert on a RED integration gate.** STOP immediately, leave
  the failed wave's merge commits local/unpushed, leave its worktrees intact
  (skip teardown), and never rewind already-pushed prior waves. Resolution is
  the user's call.
- **Teardown order is load-bearing:** kill any process still holding the
  worktree open (B2 — the Codex broker and/or the Serena LSP chain, matched by
  worktree path, not a narrow name allowlist) → confirm the dir is free →
  `worktree_remove`. These are plain helper processes — force-killing them is
  correct and safe.
- **Never merge on self-report alone (B6).** If a wave member goes idle
  without having sent its Final-step report, that is the trigger to confirm
  its real ending state directly — `git -C <worktree_path> log`/`status` plus
  `rev-list --count <branch_point_sha>..HEAD` (must be `> 0`, proving HEAD is
  ahead of the wave's branch point — not merely that a commit exists at HEAD,
  which a never-touched worktree would also show) for a landed commit, plus
  `<worktree_path>/.process-ticket-result.json` for the reviewer verdict and
  test result — not a timer, and never the self-report alone. A member that
  can't be confirmed this way (HEAD not ahead of the branch point, missing/
  unreadable marker, marker `ticket` not matching this member's actual ticket
  number, marker `verdict` not `APPROVE`, or marker `test` not `PASS`) is not
  merged; it rolls into a later wave. See Phase C step 2 for the full
  protocol.
- **Exactly one combined PR, at the very end of the run.** Individual wave
  members never open their own PR or push their own branch — `process-ticket`
  runs in `mode=integration` for every wave member specifically so this skill
  is the sole owner of the push/PR/comment steps, once, in Phase D.
- **Lane separation (load-bearing).** orchestrate-tickets runs **only** from the
  main checkout; `process-ticket` runs **only** inside a worktree on a feature
  branch. Never invoke orchestrate-tickets from a worktree, and never run
  `process-ticket` on the default branch. Each guards its own lane (see
  Preconditions here, and process-ticket's branch+worktree guard) so the
  orchestrator and the workers can't step on each other. The orchestrator session
  must not enter a worktree to make edits there directly — doing so bypasses
  planner approval, developer QA/tests, reviewer + Codex pass, and PR-based merge
  exactly as working on `main` does.
