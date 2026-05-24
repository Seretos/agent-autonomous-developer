---
name: orchestrate-tickets
description: Fleet orchestrator for a Python project — turns open tickets into parallel, conflict-free background work. Invoke to dispatch ticket work (e.g. "orchestrate tickets in acme-api", "work all open tickets in parallel", "orchestrate ticket 7 in acme-api"). With ONE ticket given it goes straight to creating a worktree and launching its instance. With none (all open) or several, it spawns the conflict-analyst subagent to find the maximal set of tickets that can run in parallel without their PRs conflicting, then creates one worktree per selected ticket and starts a background + remote-control Claude instance per worktree — idle, with no boot prompt. Plugin MCPs don't auto-load in a fresh worktree session (anthropics/claude-code#61866), so the user runs `/reload-plugins` in each session and then drives `process-ticket #<n>` there themselves. The skill creates the worktrees and starts the sessions; it does NOT prompt them, implement, push, or merge.
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

## Inputs

- A **project id** (e.g. `acme-api`). If missing or unclear, resolve it via
  `find_projects` and confirm with the user before doing anything.
- An optional ticket number, or several, or nothing.
  - **exactly one** ticket → SINGLE mode (skip analysis).
  - **none** → MULTI mode over **all open** tickets.
  - **several** → MULTI mode over **that subset**.

## Preconditions

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
**json block only**; the target set is `parallel`.

## Phase B — confirm, then create worktrees

1. **Confirm before launching.** Present the planned fleet to the user via
   **AskUserQuestion**: the tickets that will run in parallel (with branch +
   footprint), and the deferred ones with their collision reason. Launching N
   background `--dangerously-skip-permissions` sessions is heavy and
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
Windows/PowerShell:

```powershell
Push-Location '<worktree-path>'
claude --allow-dangerously-skip-permissions --verbose --rc "<branch>" --bg
Pop-Location
```

- `--rc "<branch>"` names the remote-control session after the branch; `--bg`
  detaches it under the daemon. **No trailing prompt** — the session waits idle.
- **Capture the `backgrounded · <job-id>` line** the launch prints — that
  `<job-id>` is the handle for `claude attach <job-id>` / `claude logs <job-id>`
  / `claude stop <job-id>`. Keep it in your report (Phase D) — teardown needs it.
- Do **not** open a terminal and do **not** `claude attach` — the user attaches
  when ready.

## Phase D — report

Print one table: `ticket · branch · worktree path · bg job-id`. Then spell out
the **per-session next steps the user must do** (the skill can't — see Phase C):
for each session, `claude attach <job-id>`, run **`/reload-plugins`** (so the
worktree's plugin MCPs load), then `process ticket #<n>`. Also list the deferred
tickets (what still needs a later, sequential pass) and the stop hint
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
   Then `claude stop <job-id>`. Never force-kill the process (the daemon respawns
   `--bg` jobs from their record), and never write a sidecar/state file mapping
   worktrees to job-ids.
2. **Confirm the directory is free**, then remove the worktree via the
   agent-worktree MCP (`worktree_remove`) so it releases ports, runs teardown,
   and updates its state store. Do not `rm -rf` the directory or run
   `git worktree remove` by hand — that desyncs the MCP's state.

## Hard rules

- **Project id is a parameter.** Pass the supplied `project_id` to the analyst
  and every project-issues call — never hardcode a project.
- **Delegate the analysis.** In MULTI mode the `conflict-analyst` decides the
  set; you never compute footprints yourself. In SINGLE mode you only read the
  title for a slug — no footprint analysis.
- **Conflict-free = disjoint file footprints** (the analyst's contract). Tickets
  that share a source file are never launched together; they go to `deferred`
  for a later run.
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
- **Teardown order is load-bearing:** stop the session → confirm the dir is free →
  `worktree_remove`. Resolve the job-id from history or path-match, never from a
  persisted file. Stop via `claude stop <job-id>`, never force-kill.
- **Lane separation (load-bearing).** orchestrate-tickets runs **only** from the
  main checkout; `process-ticket` runs **only** inside a worktree on a feature
  branch. Never invoke orchestrate-tickets from a worktree, and never run
  `process-ticket` on the default branch. Each guards its own lane (see
  Preconditions here, and process-ticket's branch+worktree guard) so the
  orchestrator and the workers can't step on each other.
