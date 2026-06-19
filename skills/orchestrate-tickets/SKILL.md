---
name: orchestrate-tickets
disable-model-invocation: true
description: Required entry-point for executing ticket work — one ticket, several, or all open — for a project (language/stack auto-detected). Use to split tickets, re-slice epics, and execute them. Serial/single-ticket is the normal safe path (SINGLE mode); parallel fleet is the optimisation on top. Creates one worktree per ticket. Bypassing it — working manually on `main`, or the orchestrator editing inside a worktree directly — forfeits code review, planner approval, QA/tests, Codex pass, and PR-based merge.
---

# orchestrate-tickets — fleet orchestrator

You dispatch ticket work across parallel, isolated worktrees. You decide *what*
runs (via the `conflict-analyst` subagent), create the worktrees, and stop. You
implement nothing. The user drives each worktree session independently:
`process ticket #<n>` (the `process-ticket` skill: context → plan → code →
review → draft-PR).

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
ticket gets its own worktree and its own PR.
That model has fixed overhead per ticket and a parallelism ceiling set by how
independent the tickets are. It fits some ticket shapes well and others poorly.

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
  deferred, the fixed per-ticket overhead (worktree creation, PR overhead)
  dominates over the parallelism actually gained.
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
   Determine the repo's default branch → `base`. All worktrees branch off `base`.
2. **Refresh `base` from the remote — guard against stale worktrees.** Before
   creating any worktree, bring the main checkout's default branch up to date so
   the worktrees don't branch off a stale `base`: `git fetch origin` then
   `git pull --ff-only` (you are on the default branch per Precondition 0). If it
   can't fast-forward (the local branch has diverged) or a dirty working tree
   blocks it, **STOP** and tell the user to reconcile the main checkout first —
   never merge, rebase, or force. Stopgap: `worktree_create` does **not** refresh
   from the remote itself yet, so the skill must do it here.
3. **Worktree mechanism — agent-worktree MCP only.** Worktree creation uses the
   **agent-worktree MCP** (`worktree_create`). If that MCP is **not loaded** in
   this session (fresh sessions don't auto-load plugin MCPs), **STOP** and tell
   the user to `/reload-plugins` (or do a one-time `--scope user` install of the
   plugin), then re-invoke. **Do not** fall back to raw `git worktree add` — that
   produces worktrees the MCP can't track, list, remove, or reconcile (and on
   Windows leaves locked/ports-leaked state on teardown). Confirm the MCP is
   available before Phase B.

## Phase A — decide the target tickets

**SINGLE mode** (one ticket `#n`): do **not** spawn the analyst. Fetch only the
title for the branch slug — `get_ticket(project_id, n, include_comments=False,
include_relations=False)` — and form `branch = fix/<n>-<slug>` (title
lower-cased, non-alphanumerics → hyphens, ~4 words). The target set is just
`[{ticket: n, branch}]`.

**MULTI mode** (none, or several): spawn the analyst —
`Agent(subagent_type="conflict-analyst", prompt=…)` — passing `project_id` and
either "all open" or the explicit subset. It returns a readable summary and a
trailing fenced ```json block with `parallel` and `deferred` arrays. Parse the
**json block only**; the target set is `parallel`. Each `deferred` entry carries
a **`type`**: `"file-collision"` (footprint overlap) or `"logical-dependency"`
(disjoint files, but the ticket states it must come *after* an unmet predecessor —
e.g. a doc/integration ticket). Keep that `type` through to the confirm step
(Phase B) — the two kinds mean different things to the human.

## Phase B — confirm, then create worktrees

1. **Confirm before launching.** Present the planned fleet to the user via
   **AskUserQuestion**: the tickets that will run in parallel (with branch +
   footprint), and the deferred ones **grouped by `type`** — `file-collision`
   (would conflict in a shared file) vs `logical-dependency` (clean footprint but
   must wait on an unmet predecessor, with which tickets in its `depends_on`).
   Surfacing the `logical-dependency` group explicitly is the point: the parallel
   set is conflict-free **and** dependency-respecting, so the human sees that
   ordering was checked, not silently skipped. If the analyst returned **no**
   deferrals at all, state plainly that logical-ordering dependencies were
   checked and none applied — so the blind spot never stays silent.

   **Fit Warning (MULTI mode only, when `fit.verdict == "poor"`):** After
   presenting the parallel and deferred groups — and before the go-ahead question
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

   Launching N worktrees is hard to undo, so get a go-ahead (or let the user
   drop/keep tickets) first. For SINGLE mode keep it light, but still confirm
   the one launch.
2. **Create one worktree per selected ticket, SEQUENTIALLY.** Never in parallel —
   concurrent `git worktree` ops on one repo race on the index lock.
   `worktree_create(repo_root, branch=<branch>, base=<base>)`. Capture the
   returned `path` for each — **use that returned path**, never construct a
   directory from the branch name (the `fix/<n>-…` convention contains a `/`).

## Phase C — report

Print one table: `ticket · branch · worktree path`. Then list the deferred
tickets (what still needs a later, sequential pass), keeping the
`file-collision` vs `logical-dependency` split — for `logical-dependency` ones,
name the predecessors so the user knows what must land first. Then stop — the
worktrees are ready; the user drives each one from here.

## Teardown — remove a worktree

When a worktree is no longer needed (its PR merged, or the user asks to tear it
down), remove it **safely and statelessly**:

1. **Kill any orphaned Codex broker holding this worktree.** If the worktree's
   `process-ticket` run invoked the reviewer's Codex pass, a
   `node … app-server-broker.mjs --cwd <worktree-path> …` helper can still be
   running and holding the directory open — it is **not** a `claude --bg` job, so
   `claude stop` does not reach it and force-killing it triggers **no** daemon
   respawn. Kill it **before** `worktree_remove`, while git still knows the
   worktree, so the MCP's remove stays in sync. On Windows / PowerShell (surgical
   match — the broker script **and** this worktree's path):
   ```powershell
   Get-CimInstance Win32_Process |
     Where-Object {
       $_.Name -eq 'node.exe' -and
       $_.CommandLine -like '*app-server-broker.mjs*' -and
       $_.CommandLine -like '*<worktree-path>*'
     } |
     ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   ```
   The directory-lock failure is Windows-specific (POSIX lets `git worktree remove`
   unlink a directory with an open handle), but killing the orphan is good hygiene
   everywhere — POSIX equivalent: `pkill -f "app-server-broker.mjs.*<worktree-path>"`.
2. **Confirm the directory is free**, then remove the worktree via the
   agent-worktree MCP (`worktree_remove`) so it releases ports, runs teardown,
   and updates its state store. Do not `rm -rf` the directory or run
   `git worktree remove` by hand — that desyncs the MCP's state.

**Recovery — already-desynced phantom entry.** If a worktree was left desynced
(git no longer lists it, the directory persists, and the MCP still shows
`status: created`), `worktree_remove` — even with `force=true` — fails with
`fatal: '<path>' is not a working tree`. Recover by hand: kill the broker (snippet
above) → remove the directory (`Remove-Item -Recurse -Force '<worktree-path>'`) →
delete the merged local branch (`git branch -d <branch>`). The phantom MCP entry
then remains — cosmetic; no agent-worktree MCP call currently prunes it (its own
self-reconcile is tracked in the agent-worktree repo).

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
  set; you never compute footprints yourself. In SINGLE mode you only read the
  title for a slug — no footprint analysis.
- **Parallel-safe = disjoint file footprints AND no unmet logical dependency**
  (the analyst's contract). Tickets that share a source file, *or* that state an
  explicit "must come after #x" dependency on a predecessor not yet done, are
  never launched together; they go to `deferred` (tagged `file-collision` or
  `logical-dependency`) for a later run. Surface the `logical-dependency` group at
  the confirm step so the ordering check is visible, never silently skipped.
- **agent-worktree MCP only — no raw-git fallback.** If the MCP isn't loaded,
  hard-fail and tell the user to `/reload-plugins`. Never `git worktree add`.
- **Sequential, not parallel**, for worktree creation (git index lock races).
- **Teardown order is load-bearing:** kill the worktree's Codex broker → confirm
  the dir is free → `worktree_remove`. The **Codex broker** is a plain helper
  process — force-killing it is correct and safe.
- **Lane separation (load-bearing).** orchestrate-tickets runs **only** from the
  main checkout; `process-ticket` runs **only** inside a worktree on a feature
  branch. Never invoke orchestrate-tickets from a worktree, and never run
  `process-ticket` on the default branch. Each guards its own lane (see
  Preconditions here, and process-ticket's branch+worktree guard) so the
  orchestrator and the workers can't step on each other. The orchestrator session
  must not enter a worktree to make edits there directly — doing so bypasses
  planner approval, developer QA/tests, reviewer + Codex pass, and PR-based merge
  exactly as working on `main` does.
