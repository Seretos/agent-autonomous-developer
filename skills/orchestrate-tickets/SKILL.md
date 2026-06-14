---
name: orchestrate-tickets
description: Required entry-point for any ticket work — one ticket, several, or all open — for a project (language/stack auto-detected). Use to create tickets, split tickets, re-slice epics, and to execute them. Serial/single-ticket is the normal safe path (SINGLE mode); parallel fleet is the optimisation on top. Creates one worktree per ticket and starts an idle background Claude session. Bypassing this skill — working manually on `main`, or the orchestrator session entering a worktree to edit there directly — forfeits code review, planner approval, QA/tests, Codex pass, and PR-based merge — and is not permitted.
---

# orchestrate-tickets — fleet orchestrator

You dispatch ticket work across parallel, isolated worktrees. You decide *what*
runs (via the `conflict-analyst` subagent), create the worktrees, and start one
background + remote-control Claude instance per ticket — **idle, with no boot
prompt**. You implement nothing. The user drives each session: a fresh worktree
session does not have the plugin MCPs loaded yet (anthropics/claude-code#61866),
so they run `/reload-plugins` first, then `process ticket #<n>` (the
`process-ticket` skill: context → plan → code → review → draft-PR).

There is **no cwd→project auto-detection**. The `project_id` is supplied at
invocation (see Inputs); pass it to the analyst and to every project-issues call.

### Single-ticket / serial path (the normal, always-correct path)

A single non-parallelizable or foundational ticket does **not** need a fleet.
SINGLE mode (one ticket given) is the **default safe path**: it skips the
conflict-analyst entirely, creates one worktree, and starts one idle session.
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
ticket gets its own worktree, its own background Claude session, and its own PR.
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
  deferred, the fixed per-ticket overhead (worktree creation, session startup,
  `/reload-plugins`, PR overhead) dominates over the parallelism actually
  gained.
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
    segment of `path` → `obsidian-memory-gatekeeper`. Phase C then emits
    `--name "obsidian-memory-gatekeeper/fix-12-..."`.

    *Edge cases:* `_auto` (strip underscore → matches); `auto` (direct match);
    `default`, `session` (both in blocklist); `automate-api` (does **not**
    match — full-token equality, not substring); `path` and `web_url` both
    absent → fall through to "confirm with the user"; non-placeholder id
    (e.g. `acme-api`) passes silently and slash-normalisation still applies.

    This check occurs on the value returned by `find_projects`, before the
    slash-normalisation step in Phase C.
- An optional ticket number, or several, or nothing.
  - **exactly one** ticket → SINGLE mode (skip analysis).
  - **none** → MULTI mode over **all open** tickets.
  - **several** → MULTI mode over **that subset**.

## Preconditions

0. **Name the orchestrator session at launch time (user responsibility).** The
   orchestrator session is already running when this skill is invoked, so its
   display name should be set by the user at launch time via `--name "<project_id>"` — e.g.
   `claude --name "acme-api" --permission-mode bypassPermissions --allow-dangerously-skip-permissions`.
   The skill cannot enforce this at runtime; if the user omits `--name`, the
   session gets an auto-generated name. As a mid-flight fallback, `/rename <name>`
   is available inside a running session to set the display name after launch.

1. **Run only from the main checkout — never inside a worktree.** This skill is
   the mirror of `process-ticket` (which runs only *inside* a worktree on a
   feature branch). Guard before doing anything else:
   - `git rev-parse --abbrev-ref HEAD` must be the repo's default branch.
   - `git rev-parse --git-dir` must EQUAL `git rev-parse --git-common-dir`
     (they differ when you are inside a linked worktree).
   If either check fails, **STOP** and tell the user to run orchestrate-tickets
   from the project's main checkout — otherwise the worktrees it spawns and the
   orchestrator's own branch/state collide with the workers.
2. **Capture repo + base branch.** `git rev-parse --show-toplevel` → `repo_root`.
   Determine the repo's default branch → `base`. All worktrees branch off `base`.
3. **Refresh `base` from the remote — guard against stale worktrees.** Before
   creating any worktree, bring the main checkout's default branch up to date so
   the worktrees don't branch off a stale `base`: `git fetch origin` then
   `git pull --ff-only` (you are on the default branch per Precondition 1). If it
   can't fast-forward (the local branch has diverged) or a dirty working tree
   blocks it, **STOP** and tell the user to reconcile the main checkout first —
   never merge, rebase, or force. Stopgap: `worktree_create` does **not** refresh
   from the remote itself yet, so the skill must do it here.
4. **Worktree mechanism — agent-worktree MCP only.** Worktree creation uses the
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

   Launching N background `--permission-mode bypassPermissions --allow-dangerously-skip-permissions` sessions is heavy and
   hard-to-undo, so get a go-ahead (or let the user drop/keep tickets) first.
   For SINGLE mode keep it light, but still confirm the one launch.
2. **Create one worktree per selected ticket, SEQUENTIALLY.** Never in parallel —
   concurrent `git worktree` ops on one repo race on the index lock.
   `worktree_create(repo_root, branch=<branch>, base=<base>)`. Capture the
   returned `path` for each — **use that returned path**, never construct a
   directory from the branch name (the `fix/<n>-…` convention contains a `/`).

## Phase C — launch one instance per worktree

For each created worktree, **sequentially**, start a background + remote-control
Claude instance whose working directory is the worktree (so the user's later
`process-ticket` run passes its branch guard — it must run on a feature branch,
never on the default branch). Start it **idle — no boot prompt**: a freshly-spawned
worktree session does not have the plugin MCPs loaded, so a boot prompt would fail
before the user can `/reload-plugins` (see anthropics/claude-code#61866). On
Windows/PowerShell, use the literal `path` field returned by `worktree_create`
as `<worktree-path>` — never reconstruct the path from the branch name, and
never assume `.claude/worktrees/` or any other base directory (mirroring the
Phase B discipline). **This snippet is PowerShell-only — do NOT paste it into
bash or cmd.** Under bash, `Set-Location` is "command not found" and execution
silently continues, so `claude --bg` would launch from the wrong cwd. The snippet:

```powershell
Set-Location '<worktree-path>' -ErrorAction Stop
if ($PWD.Path -ne '<worktree-path>') { throw "cwd guard: expected '<worktree-path>', got $($PWD.Path) — aborting before launch" }
claude --allow-dangerously-skip-permissions --permission-mode bypassPermissions --verbose --name "<project_id>/<branch-slug>" --bg
```

  Where `<branch-slug>` is the branch name with every internal `/` replaced by
  `-` (so `fix/12-add-login` becomes `fix-12-add-login`), giving a session name
  like `acme-api/fix-12-add-login`. After placeholder resolution (see Inputs)
  and before slash-normalisation, the project id must already be a
  non-placeholder slug. Then: if the project id itself contains a `/`
  (e.g. an org-scoped id like `acme/api`), replace those slashes with `-` too
  (yielding `acme-api`), so exactly one slash — the separator between project id
  and branch slug — remains in the session name. No nested slashes.

- `--name "<project_id>/<branch-slug>"` sets the display name shown in the
  Claude Agents overview and `/resume` picker, so both the project and the ticket
  branch are identifiable at a glance; `--bg` detaches it under the daemon.
  **No trailing prompt** — the session waits idle.
- **Capture the `backgrounded · <job-id>` line** the launch prints — that
  `<job-id>` is the handle for `claude attach <job-id>` / `claude logs <job-id>`
  / `claude stop <job-id>`. Keep it in your report (Phase D) — teardown needs it.
- **Verify the session's cwd immediately after launch (mandatory, not advisory).**
  Run `claude agents --json`, find the entry whose `id` matches `<job-id>`, and
  assert its `cwd` field equals the `path` returned by `worktree_create`. If they
  do not match, run `claude stop <job-id>` immediately and report an error — **do
  NOT proceed to Phase D**. A session running from the wrong directory will fail
  the `process-ticket` branch guard and produce corrupt work.
- Do **not** open a terminal and do **not** `claude attach` — the user attaches
  when ready.

## Phase D — report

Print one table: `ticket · branch · worktree path · bg job-id`. Then spell out
the **per-session next steps the user must do** (the skill can't — see Phase C):
for each session, `claude attach <job-id>`, run **`/reload-plugins`** (so the
worktree's plugin MCPs load), then `process ticket #<n>`. Also list the deferred
tickets (what still needs a later, sequential pass), keeping the
`file-collision` vs `logical-dependency` split — for `logical-dependency` ones,
name the predecessors so the user knows what must land first — and the stop hint
(`claude stop <job-id>`). Then stop — you've started the fleet; the user drives
it from here.

## Teardown — stop the session before removing a worktree

When a worktree is no longer needed (its PR merged, or the user asks to tear it
down), remove it **safely and statelessly**:

1. **Stop the worktree's background Claude session first.** A live `claude --bg`
   session holds the worktree directory open — on Windows `worktree_remove` will
   fail with a lock while it runs. Resolve the session's `<job-id>` **without any
   stored state**, by either:
   - reading it from **this orchestrator's own launch history** — the
     `backgrounded · <job-id>` line Phase C printed for that worktree; or
   - **matching the worktree path** to a running background job (list the bg jobs
     and pick the one whose working directory is this worktree).
   Then `claude stop <job-id>`. Never force-kill the *session* process (the daemon
   respawns `--bg` jobs from their record), and never write a sidecar/state file
   mapping worktrees to job-ids.
2. **Kill any orphaned Codex broker holding this worktree.** If the worktree's
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
3. **Confirm the directory is free**, then remove the worktree via the
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
  in any session `--name` or Phase D report, verify it does not match the
  blocklist: strip any leading `_`, then compare case-insensitively against
  `auto`, `default`, and `session`. If it matches, derive a slug from the last
  path segment of the `path` or `web_url` field from the `find_projects` result
  (e.g. `Seretos/obsidian-memory-gatekeeper` → `obsidian-memory-gatekeeper`).
  If no unambiguous slug is available (both fields absent or empty), confirm
  with the user. A non-placeholder id (e.g. `acme-api`) passes silently;
  slash-normalisation still applies afterwards.
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
- **Sequential, not parallel**, for both worktree creation and instance launch
  (git index lock + bg-session registration races).
- **Each instance runs in its own worktree on its feature branch.** Never launch
  an instance with cwd on the default branch.
- **You start sessions idle; you don't prompt, implement, push, or merge.** The
  user runs `/reload-plugins` then `process-ticket` in each session — that owns
  implementation and its own draft PR. You stop after launching + reporting.
- **`/reload-plugins` is mandatory in each spawned session before `process-ticket`** —
  fresh worktree sessions don't auto-load the plugin MCPs
  (anthropics/claude-code#61866). That's why sessions start idle, not with a
  `process-ticket` boot prompt.
- **Teardown order is load-bearing:** stop the session → kill the worktree's Codex
  broker → confirm the dir is free → `worktree_remove`. Resolve the job-id from
  history or path-match, never from a persisted file. Stop the **session** via
  `claude stop <job-id>`, never force-kill it (the daemon respawns `--bg` jobs); the
  **Codex broker** is a plain helper process — force-killing it is correct and safe.
- **Phase C launch snippet must run in PowerShell — not bash, not cmd.** Under
  bash, `Set-Location` and `Push-Location` are "command not found" and execution
  silently continues, so `claude --bg` launches from the wrong cwd (the main
  checkout) — exactly the problem the snippet's cwd guard is designed to prevent.
  The post-launch `claude agents --json` cwd-check (see Phase C) is the runtime
  backstop but does **not** excuse running the snippet in the wrong shell: by the
  time that check fires, a dangerous session has already started. See Phase C for
  the full snippet and its required form.
- **Lane separation (load-bearing).** orchestrate-tickets runs **only** from the
  main checkout; `process-ticket` runs **only** inside a worktree on a feature
  branch. Never invoke orchestrate-tickets from a worktree, and never run
  `process-ticket` on the default branch. Each guards its own lane (see
  Preconditions here, and process-ticket's branch+worktree guard) so the
  orchestrator and the workers can't step on each other. The orchestrator session
  must not enter a worktree to make edits there directly — doing so bypasses
  planner approval, developer QA/tests, reviewer + Codex pass, and PR-based merge
  exactly as working on `main` does.
