---
name: orchestrate-tickets
disable-model-invocation: true
description: Required entry-point for executing ticket work — one ticket, several, or all open — for a project (stack auto-detected). Use to split tickets, re-slice epics, and execute them. Serial/single-ticket is the normal safe path (SINGLE mode); MULTI mode drives a multi-ticket fleet across ordered waves, sequential process-ticket(mode=integration) runs into a shared integration branch, gated per wave, ending in exactly one combined draft PR. Bypassing it — manual work on `main`, or editing inside a worktree directly — forfeits code review, planner approval, QA/tests, Codex pass, and PR-based merge.
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
  - **none** → MULTI mode over **all open** tickets. This is the **only**
    path subject to the board-driven backlog release gate — see Phase A.
  - **several** → MULTI mode over **that subset**.

## Preconditions

**Bootstrap — capture `repo_root` first, before anything else.**
`git rev-parse --show-toplevel` → `repo_root`. This is the **one intentional
ambient git call** in this skill: every other git invocation below (and
throughout Phase C, Phase D, and Teardown) is pinned with `git -C
<repo_root> …` so it never depends on the shell's persisted/ambient cwd —
which background/job-mode invocations can silently reset between tool calls,
potentially onto one of the fleet's own worker worktrees (see AGENTS.md's
cwd-independent-git invariant). This one call is unavoidably ambient — you
cannot `-C` into a root you have not yet discovered — but a wrong resolution
here is caught immediately by Precondition 0's `--git-dir`/`--git-common-dir`
check below, which itself runs `-C <repo_root>` and fails closed if
`repo_root` was miscaptured as a worktree.

0. **Run only from the main checkout — never inside a worktree.** This skill is
   the mirror of `process-ticket` (which runs only *inside* a worktree on a
   feature branch). Guard before doing anything else:
   - `git -C <repo_root> rev-parse --abbrev-ref HEAD` must be the repo's
     default branch.
   - `git -C <repo_root> rev-parse --git-dir` must EQUAL
     `git -C <repo_root> rev-parse --git-common-dir` (they differ when
     `repo_root` resolved to a linked worktree).
   If either check fails, **STOP** and tell the user to run orchestrate-tickets
   from the project's main checkout — otherwise the worktrees it spawns and the
   orchestrator's own branch/state collide with the workers.
1. **Determine the base branch.** Determine the repo's default branch → `base`
   (`repo_root` was already captured in the Bootstrap step above). `base` is
   only the starting point for the run's integration branch (step 3) —
   worktrees branch off the **integration branch's current head**, not `base`
   directly (see Phase C).
2. **Refresh `base` from the remote — guard against stale worktrees.** Before
   creating any worktree, bring the main checkout's default branch up to date so
   the integration branch doesn't start from a stale `base`:
   `git -C <repo_root> fetch origin` then `git -C <repo_root> pull --ff-only`
   (you are on the default branch per Precondition 0).
   If it can't fast-forward (the local branch has diverged) or a dirty working
   tree blocks it, **STOP** and tell the user to reconcile the main checkout
   first — never merge, rebase, or force. Stopgap: `worktree_create` does
   **not** refresh from the remote itself yet, so the skill must do it here.
3. **Create the shared integration branch.** After the refresh above, create a
   run-scoped integration branch off the freshly-pulled `base`:
   `git -C <repo_root> branch <integration> <base>` where `<integration>` is
   `integration/<run-slug>` (`<run-slug>` — a short, unique identifier for this
   run, e.g. a date-stamp plus the lead ticket number, such as
   `integration/2026-07-13-171`). Push it once right away:
   `git -C <repo_root> push -u origin <integration>`. Capture `<integration>` —
   every wave's worktrees, merges, and the final combined PR all key off this
   one branch for the rest of the run.
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

**MULTI mode** (none, or several): before spawning the analyst on the
**implicit "none"/"all open" path only**, run the backlog release gate below.
SINGLE mode bypasses it entirely — no board lookup, no analyst call at all —
and an explicit MULTI ticket subset ("several") bypasses it too, exclusively:
the human already named those tickets by number, so a board column must never
override an explicit selection.

**Backlog release gate (`none`/"all open" path only).** Call
`list_board_columns(project_id)` to detect a release gate before deciding the
candidate set:

- **No board configured** → zero behavior change: skip the filter entirely
  and proceed exactly as before, over all open tickets. `list_board_columns`
  signals "no board configured" one of two ways, and **only** these two count
  as that signal: a stable non-error empty result, `columns: []`; or an error
  whose message specifically and distinguishably identifies a missing/
  misconfigured `board` block — i.e. the board is absent or not set up, not
  that the call itself malfunctioned. Catch **only** that specific "board not
  configured" error signal and treat it the same as the empty-result case:
  skip the filter. Do **not** widen the catch beyond that one signal: any
  other error from `list_board_columns` — an auth failure, a network/
  provider outage, a rate limit, a permission error, or any error whose
  message does not clearly and distinguishably identify a missing/
  misconfigured board — must **surface and STOP** Phase A rather than being
  silently treated as "no board configured." Degrading a transient or
  ambiguous failure to "no board" would silently let Backlog-parked tickets
  back into the candidate set, which this gate exists to prevent.
- **Board present but no column literally named `Backlog`** → the
  `Backlog`-column drop does not apply. The match is **exact/full-token**,
  not substring (mirrors this file's existing `_auto`/`automate-api`
  full-token-equality convention in Inputs above) — a column named
  `Backlog Items` or `old-backlog` does **not** match. This does **not**
  mean the filter is skipped entirely, though: since a board is configured
  (just without a `Backlog` column), the untriaged drop below still fires —
  enumerate open tickets and drop any that were never triaged onto the
  board at all (no board Status/column value set — e.g. filed via
  `create_ticket` and never added to the board) before the analyst ever
  sees them.
- **Otherwise** (a column literally named `Backlog` exists): enumerate open
  tickets and drop any ticket whose current board column is `Backlog`, **and**
  any ticket that was never triaged onto the board at all (no board Status/
  column value set), before the analyst ever sees either kind. Pass the
  survivors to the analyst as an explicit subset in place of "all open".
  - **Zero-survivors guard.** If the filter empties the candidate set, state
    so plainly and **STOP** — never spawn the conflict-analyst over an empty
    fleet.
- This gate is **provider-agnostic**: it relies solely on
  `list_board_columns`, which already normalizes the underlying board/column
  model for the connected provider — never hardcode provider-specific column
  semantics here.
- **Read/filter-only.** This gate only reads board state to decide the
  candidate set; it never moves a ticket, writes a comment, or otherwise
  mutates anything. Sibling ticket #77 owns the write side.

Then spawn the analyst —
`Agent(subagent_type="conflict-analyst", prompt=…)` — passing `project_id`
and the candidate set, which is always one of two things: **"all open"**
— the unfiltered open set, used only when the gate was skipped above
entirely (no board configured) — or **the explicit subset**, used in every
other case, including a board present but with no `Backlog` column (the
untriaged drop can still fire there): on the "none" path once the gate actually fires, the
survivors are passed as the explicit subset, the same mechanism as the
"several" bypass case, and are never re-described as "all open" once
filtered; on the "several" path it is always the explicit subset the human
named by number, which bypasses the gate entirely. It returns a readable summary
and a trailing fenced ```json block with `waves` and `deferred` arrays. Parse
the **json block only**; the target set is the ordered `waves` array — a list of
parallel-safe sets (`waves[0]`, `waves[1]`, …), each element keeping the
`ticket`/`branch`/`title`/`files`/`scope` shape. Each `deferred` entry carries
a **`type`**: `"file-collision"` (footprint overlap) or `"logical-dependency"`
(disjoint files, but the ticket states it must come *after* an unmet predecessor —
e.g. a doc/integration ticket). Keep that `type` through to the confirm step
(Phase B) — the two kinds mean different things to the human.

## Phase B — confirm the fleet

Define a **clean run**: SINGLE mode, OR MULTI mode with `fit.verdict == "good"`
AND `deferred` empty. This is the one precise condition this phase branches
on — there is no flag, no persisted preference, and no opt-back-in escape
hatch; the branch below is the entire logic.

**Backlog-skip group — distinct from `deferred`, display-only.** If Phase A's
backlog release gate dropped any tickets — whether parked in a `Backlog`
board column or never triaged onto the board at all (no board Status/column
value set) — surface them together as their own group —
**"N tickets skipped — still in Backlog"** — separate from and never merged
into `deferred`: a `deferred` entry means the analyst considered the ticket
and set it aside for a file-collision or logical-dependency reason; a
backlog-skip entry (Backlog-column or untriaged) never reached the analyst
at all. This group is **display-only**: it does not force the interactive
AskUserQuestion gate and
adds no clause to the clean-run predicate above — a run with a non-empty
backlog-skip group but an empty `deferred` list and `fit.verdict == "good"`
is still a clean run. It is shown in whichever Phase B message actually
prints for the run: the non-interactive clean-run status message (item 1) or
the interactive gate body (item 2), never both, matching whichever path this
run takes.

1. **Clean run — skip the interactive gate by default.** A clean run
   proceeds without the interactive AskUserQuestion gate by default: do
   **not** call **AskUserQuestion**, and do not block on any response. Proceed
   straight to Phase C — but still emit a plain, non-interactive status
   message so an attended user sees what it did: the waves in order (each
   wave's tickets, with branch + footprint), and — for the clean MULTI case —
   the one-line statement that logical-ordering dependencies were checked and
   none applied (consistent with `deferred` being empty). If Phase A's
   backlog release gate skipped any tickets, this status message also carries
   the distinct **"N tickets skipped — still in Backlog"** group (see below)
   — display-only, it never blocks or alters this skip-the-gate branch. This
   status message is the same information item 2 below would otherwise ask
   the human to confirm; the only difference is it is printed, not gated on a
   response.

2. **Otherwise — mandatory go-ahead gate, unchanged and never skipped.**
   Whenever `fit.verdict == "poor"` (the Fit Warning path) OR a non-empty
   `deferred` list is present, the interactive gate stays **mandatory** —
   these two cases are **never skipped**, regardless of how trivial the rest
   of the run looks.
   Present the planned fleet to the user via **AskUserQuestion**: the waves in
   order (each wave's tickets, with branch + footprint), and the deferred ones
   **grouped by `type`** — `file-collision` (would conflict in a shared file)
   vs `logical-dependency` (clean footprint but must wait on an unmet
   predecessor, with which tickets in its `depends_on`). Surfacing the
   `logical-dependency` group explicitly is the point: each wave is
   conflict-free **and** dependency-respecting, so the human sees that
   ordering was checked, not silently skipped. This branch also fires for a
   poor-fit run whose `deferred` list is empty — in that case there is no
   `logical-dependency` group to surface, so state plainly that logical-
   ordering dependencies were checked and none applied, the same statement
   item 1's clean-run path makes, so the blind spot never stays silent. If
   Phase A's backlog release gate skipped any tickets, this gate body also
   presents the distinct **"N tickets skipped — still in Backlog"** group
   (see above) alongside the deferred groups — still display-only, it adds no
   new question and does not change what the go-ahead prompt below asks.

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

   Launching N worktrees across M waves is hard to undo, so get a go-ahead (or
   let the user drop/keep tickets) first in either of these two mandatory
   cases.

## Phase C — the wave loop

Iterate the `waves` array **wave-by-wave, in order**. For each wave:

1. **Create that wave's worktrees, SEQUENTIALLY.** Never in parallel —
   concurrent `git worktree` ops on one repo race on the index lock.
   `worktree_create(repo_root, branch=<branch>, base=<integration>)` — branch
   off the **current integration-branch head**, not `base` directly, so each
   wave builds on top of everything already merged from earlier waves. Capture
   the returned `path` for each — **use that returned path**, never construct a
   directory from the branch name (the `fix/<n>-…` convention contains a `/`).
2. **Drive `process-ticket` per member, SEQUENTIALLY, one at a time — never in
   parallel.** For every ticket in the wave, **in order**, invoke
   `process-ticket` with `mode=integration` and `worktree_path=<path>` (the
   path captured above) as a **fresh, synchronous, unnamed** spawn, mirroring
   the exact pattern `process-ticket`'s own Phase 2-4 already use for the
   planner/developer/reviewer (see `skills/process-ticket/SKILL.md`: "Do not
   pass a `name`... always fresh synchronous unnamed Agent() calls"). Wait for
   that one dispatch's synchronous reply — verdict (`APPROVE`/
   `CHANGES_REQUESTED`) and test result (`PASS`/`FAIL`) — before starting the
   next member's dispatch. Never issue a second wave member's dispatch while
   one is still outstanding, and never `SendMessage` an already-dispatched
   member instead of waiting for its one synchronous reply. Each member still
   runs the full Phase 1-4 pipeline (context → plan → code → review) and does
   its own local commit, but does **not** push, open a PR, or comment on the
   PR/link — this skill owns that, once, at the end of the whole run
   (Phase D). `process-ticket` itself now posts short status comments to the
   ticket after Phase 3 and Phase 4 (test result, review verdict — see
   `skills/process-ticket/SKILL.md`'s Phase 3/4 notes), so the ticket carries
   a durable trail of how far a run got even if the orchestrator session
   itself dies mid-run.

   **Root cause eliminated, not compensated for (ticket #88).** The previous
   design drove wave members **in parallel**, which necessarily meant each
   was a background/named `Agent` spawn — the only mechanism that runs
   concurrently. That is the same delivery mechanism whose failure mode
   caused the planner-spawn deadlock originally fixed in **#58/#60** (a
   named spawn switches into background/mailbox delivery, and the callee has
   no `SendMessage` tool to push a reply back if that delivery silently
   drops) — see `skills/process-ticket/SKILL.md`'s Phase 2 note for the
   original case. A live incident (ticket #88) found this surfacing at the
   wave-member level repeatedly in one run: duplicate developer instances
   racing concurrently in the same worktree, a report arriving at the wrong
   parent, and separately, a developer ending its turn without ever starting
   its mandated test run — each one silent, discovered only by manual
   follow-up. Sequential, unnamed dispatch removes the precondition for all
   of these at once, rather than compensating for them after the fact: there
   is never more than one open dispatch at a time, so there is never a
   report with an ambiguous recipient, and never a reason to `SendMessage` a
   running dispatch instead of simply waiting for its one synchronous reply
   or re-dispatching it fresh. This is why the git-state/marker-file
   self-healing apparatus that used to live here (formerly documented as
   `AGENTS.md`'s "B6" safeguard) is gone rather than merely narrowed: the
   orchestrator now always gets each member's real, complete ending state
   directly from that member's own synchronous report, so there is nothing
   left to reconstruct from git state or a result-marker file.

   **Merge criterion — directly from the report, the only mechanism.** A
   member counts as approved-and-green simply when its Phase-4 report shows
   `VERDICT: APPROVE` **and** a `PASS` test result — read straight off the
   synchronous reply this step already waited for. No fallback, no
   self-report-versus-git-state cross-check is needed or performed. A member
   that ends `CHANGES_REQUESTED`, or reports a failing test run, is **not
   merged**; it rolls into a later (possibly solo, single-member) wave for a
   subsequent run — see step 4 below.
3. **Checkout the integration branch, then B4 — clean-checkout gate, before
   any merge.** On the main checkout (`repo_root`), first switch onto the
   integration branch itself: `git -C <repo_root> checkout <integration>` (or
   `git -C <repo_root> switch <integration>`) — the checkout stayed on `base`
   since Precondition 0/3, and the merges in step 4 below must land on
   `<integration>`, not `base`. Then confirm there is nothing uncommitted
   sitting in the way of the merges about to happen:
   `git -C <repo_root> status --porcelain` and `git -C <repo_root> diff` must
   both be **empty**. If either is non-empty, **STOP** — do not merge into a
   dirty integration-branch checkout.
4. **Merge approved + green members into the integration branch.** For every
   member that ended `APPROVE` with a green test run, merge its branch with
   `git -C <repo_root> merge --no-ff <branch>` into `<integration>`. Members
   that were `CHANGES_REQUESTED` or reported failing tests are **dropped from
   this merge** — no special handling needed, they simply roll into a later
   (possibly solo, single-member) wave for a subsequent run.
5. **Integration gate — run the full suite on the integration branch**, after
   merging the wave's approved members. This is the cross-wave safety net: it
   catches interactions between this wave's changes and everything merged so
   far, which no single member's own test run could see. The test runner
   itself is the one non-git, cwd-dependent step in this skill — `-C` has no
   test-runner equivalent — so make its first statement an explicit
   `Set-Location <repo_root>` (PowerShell) / `cd <repo_root>` (POSIX) before
   invoking the detected test command; this is not a strategy mix with the
   `-C` convention above, it is the one place where a location change (rather
   than a per-command flag) is the only option. This is a **full-suite run**,
   so — after that `Set-Location`/`cd` — it uses the same backgrounded
   `nohup <detected-test-cmd> > <log> 2>&1 &` + in-turn `Monitor` pattern
   mandated for sub-agents (never a plain foreground call, which is subject
   to the tool's ~10-minute timeout that the suite's real runtime reliably
   exceeds).
   - **On GREEN:** tear down this wave's worktrees (see Teardown below, with
     the B2/B3 extensions), **then push the integration branch** —
     `git -C <repo_root> push origin <integration>` is a **hard precondition
     before the next wave creates any worktree (B1)**. Never let a later wave
     branch off an unpushed integration head.
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
   resolution from a RED gate), and — if non-empty — the run's
   `manual-cleanup-needed` list from Teardown step 3 (self-cwd-locked worktree
   directories that need a human to delete them by hand), so stale
   directories are always flagged, never silently accumulated.
4. **Switch the main checkout back to the default branch.** The main checkout
   has been sitting on `<integration>` since Phase C step 3; now that the
   combined PR is open, `git -C <repo_root> checkout <base>` (or
   `git -C <repo_root> switch <base>`) so Precondition 0 holds again for the
   next invocation of this skill.

**No completion column written (ticket #77).** Phase D writes NO completion
column here — no `Done` write is introduced anywhere in this phase. Each
merged ticket's board card stays wherever `process-ticket` last left it
(`Review`, if a board is configured — see AGENTS.md's Board card movement
section) until a human, or the real PR-merge event, later transitions it to
`Done`. Everything else in this phase (one combined draft PR + one
link-comment per ticket) is otherwise unchanged by this note.

## Teardown — remove a worktree

When a worktree is no longer needed (its wave's integration gate went green
and it has been merged, or the user asks to tear one down after resolving a
RED gate), remove it **safely and statelessly**:

1. **B2-match / B2-kill — kill any process still holding this worktree
   open.** A `process-ticket` run can leave more than one long-lived helper
   bound to the worktree directory: the reviewer's optional Codex pass
   spawns `node … app-server-broker.mjs --cwd <worktree-path> …`, and Serena
   navigation tooling can leave its LSP chain (`node`, `uvx`/`uv`,
   `serena.exe`, `python.exe`) running against the same path. None of these
   are `claude --bg` jobs, so `claude stop` does not reach them, and
   force-killing them triggers **no** daemon respawn. This kill is split into
   two named halves — matching, then killing — so the matching logic lives
   in exactly one place rather than being restated inline:
   - **B2-match** — the shared matching primitive. Given a worktree path, it
     yields the survivor PID set: every process whose command line or cwd
     references that worktree path, **with the orchestrator's own process
     tree excluded**. B2-kill (below) consumes this survivor set directly;
     nothing restates the matching logic inline.
   - **B2-kill** — the B2-only consumer of B2-match's survivor set: the
     existing exe-name allowlist + `app-server-broker.mjs` filter, then
     `Stop-Process`/`kill` the result.

   **Env-var indirection — a separate preceding statement, always.** Before
   B2-match ever runs, assign the worktree path to an env var in its own
   preceding statement — never inline with the match itself:
   - Windows/PowerShell: `$env:AAD_WORKTREE = '<worktree-path>'` as a
     preceding statement; the matcher then reads `"*$env:AAD_WORKTREE*"` —
     never the literal path substituted directly into the match expression.
   - POSIX: `export AAD_WORKTREE='<worktree-path>'` as a preceding
     statement; the matcher then reads `"$AAD_WORKTREE"`.
   This is a *separate* preceding statement so the match expression itself
   never needs the literal path re-embedded in its text.

   **Correction (ticket #86) — statement separation alone does not
   prevent self-matching; PID-exclusion does.** An earlier version of this
   note implied that keeping the assignment as a separate preceding
   statement was itself "the root cause fix" for self-matching. That
   overstates it. When the assignment and the match are issued as **one
   single shell invocation** — a single `powershell -Command "..."` /
   `sh -c "..."` string, the pattern this plugin uses elsewhere (e.g. the
   `nohup <detected-test-cmd> > <log> 2>&1 &` dispatch used by Phase C step
   5's integration-gate test run) — the *wrapping* process's own command-line
   argument is the
   entire script text, and that text still contains the literal worktree
   path baked into the assignment statement. A naive command-line
   substring/wildcard scan would therefore still match that wrapping
   process against itself, regardless of how many logical statements the
   script is broken into — statement separation by itself does not change
   what appears in the wrapping process's own command line. What actually
   prevents the wrapping process from self-matching is the
   **self/ancestor/descendant PID-exclusion** documented immediately below:
   the wrapping process's own PID is `$PID`/`$$` inside the script it is
   currently executing, so it is always a member of the self-exclusion set
   computed before anything is matched or killed. **PID-exclusion is the
   load-bearing protection against the single-invocation self-match
   scenario.** Env-var indirection's real, distinct benefit is different: it
   avoids re-embedding/duplicating the literal (and potentially
   special-character-laden) worktree path directly inside the match
   expression text itself — one assignment, one source of truth, referenced
   by variable everywhere the match runs — not self-match prevention on its
   own.

   **Empty/unset env-var fail-safe — zero survivors, never a wildcard
   match.** If the environment variable doesn't persist between calls (e.g.
   a fresh shell per invocation lost the assignment), the matcher must
   **never** fall through to evaluating an unscoped wildcard: on Windows,
   `-like "*$env:AAD_WORKTREE*"` silently degrades to `-like "**"` when the
   variable is empty, which matches **every** process's command line; on
   POSIX, `pgrep -f "$AAD_WORKTREE"` degrades to matching **every** process
   on the system. Neither is a narrowed-but-still-useful match — both are a
   total loss of worktree-path scoping, and the self/ancestor/descendant PID
   exclusion filter does **not** rescue this case: that filter only removes
   self/ancestors/descendants from an already-matched set, it does nothing
   to stop a wildcard from matching unrelated system processes in the first
   place (processes B2-kill could then mass-kill if they happen to satisfy
   its exe-name/broker allowlist). The correct guarantee, and the one both
   B2-match recipes below
   implement: **before the match expression ever runs, verify the env var is
   non-empty/set; if it is empty or unset, B2-match immediately yields an
   EMPTY survivor set — zero processes, full stop.** This is a fail-safe
   independent of the PID-exclusion layer, not a restatement of it.

   **Self/ancestor/descendant PID exclusion — evaluated per candidate, never
   a pre-match snapshot subtraction (ticket #86).** An earlier version of
   this recipe built one exclusion set up front — the orchestrator's own
   PID, plus a snapshot of its ancestor chain, plus a snapshot of its
   descendant tree — and subtracted that set from B2-match's raw match
   result. That is insufficient: in the documented single
   `sh -c "AAD_WORKTREE=…; …"` invocation form, the matcher's own pipeline
   forks new processes *after* any such snapshot was taken — most notably
   `candidates=$(pgrep -f "$escaped_worktree")`, whose command substitution
   runs inside a **subshell**. That subshell's own `/proc/<pid>/cmdline` can
   still read as the **parent shell's** full command line (the same script
   text that carries the literal worktree path baked into the earlier
   assignment statement), and its cwd can sit inside the worktree too — a
   genuine match candidate. In POSIX `sh`, `$$` inside a subshell still
   resolves to the **parent's** PID, not the subshell's own, so that
   subshell's real PID is neither `$$` itself nor a member of a descendant
   snapshot taken moments earlier, and `pgrep` excludes only its own PID
   from its results, never its caller's subshell. Net effect: a survivor
   that is the orchestrator's own process can leak straight through
   B2-kill — the exact same self-match failure mode ticket
   #86 exists to fix, just relocated one layer down into the matcher's own
   forked pipeline. A pre-match snapshot cannot contain a process the
   matcher's own pipeline forks *after* the snapshot was taken; only a
   check performed **per candidate, using each candidate's own live parent
   linkage,** closes this gap.

   The fix: exclusion is evaluated **per candidate**, never as a set
   precomputed once and subtracted. For every PID in B2-match's raw match
   result, walk that candidate's own parent-PID chain upward — `ppid` on
   POSIX, `ParentProcessId` on Windows — and discard the candidate if the
   chain reaches the orchestrator's own PID (`$PID`/`$$`) or any PID already
   known to be one of the orchestrator's own ancestors. This walk runs
   **before anything is killed or counted toward liveness** — the same
   invariant as before, just applied per candidate instead of via a
   precomputed set. Because the walk starts from the candidate's
   own, already-existing PID and asks "what is your parent, and your
   parent's parent" using the same self/ancestor/descendant linkage data,
   it correctly reaches a subshell's parent even when that subshell was
   forked after any earlier snapshot — there is no stale forward-computed
   descendant-tree set to have missed it in the first place.
   - Windows/PowerShell: derive a pid→`ParentProcessId` lookup map from the
     single `Get-CimInstance Win32_Process` snapshot B2-match already
     captured for command-line matching, then for each raw-match candidate
     walk that map upward from the candidate's own PID until it either
     reaches `$PID` (self/ancestor/descendant exclusion) or runs out of
     ancestors to walk.
   - POSIX: build the same pid→`ppid` lookup from B2-match's own descendant
     discovery data — a primary/fast path and a portable fallback: on
     Linux, a forward walk over `/proc/*/stat` (fast, reading each
     process's `ppid` from its stat entry); where `/proc` is unavailable
     (macOS/BSD), a walk over `ps -eo pid,ppid` output instead — then for
     each raw-match candidate PID, walk that lookup upward from the
     candidate's own PID (`ppid`, `ppid`'s `ppid`, …) until it either
     reaches `$$` (the orchestrator's own PID) or runs out of ancestors.
     This keeps the self/ancestor/descendant exclusion — and therefore the
     "excluded by construction" guarantee stated throughout this file —
     genuinely platform-independent, not Linux-`/proc`-only, while fixing
     the pre-match-snapshot gap above.

   **B2-match, Windows/PowerShell** (command-line matching only —
   `Win32_Process` exposes no per-process cwd, so "prefer cwd matching where
   the platform allows" is scoped to POSIX below, not Windows; command-line
   matching alone already covers the worktree path, so no separate `Path`/
   `ExecutablePath` clause is added). This produces the same broad,
   unfiltered survivor set as POSIX's B2-match below — self/ancestor/
   descendant exclusion and path matching only, **no exe-name filtering**.

   **Wildcard-escaping (ticket #86).** `-like` treats
   `*`, `?`, `[`, `]` as pattern metacharacters, not literal text. `*` and
   `?` cannot appear in a Windows path (NTFS forbids them), but `[` and `]`
   are legal path characters — an unescaped `[3]` in a worktree path is
   read as "one char, either `3`" rather than the literal three characters
   `[`, `3`, `]`, which makes the match **fail to find** a genuinely
   matching process (verified: `'...[3]...' -like "*...[3]...*"` returns
   `$false` when the pattern text is the unescaped raw path). The fix is to
   escape the path with the built-in
   `[System.Management.Automation.WildcardPattern]::Escape()` before
   building the `-like` pattern — never hand-roll the escaping. The
   self/ancestor/descendant exclusion walk above is concrete here, not a
   placeholder — it derives its pid→`ParentProcessId` map from this same
   `Get-CimInstance Win32_Process` snapshot, then walks that map per
   candidate:
   ```powershell
   $env:AAD_WORKTREE = '<worktree-path>'
   if ([string]::IsNullOrEmpty($env:AAD_WORKTREE)) {
     # Fail-safe: empty/unset AAD_WORKTREE must never fall through to the
     # wildcard match below (`-like "**"` would match every process). Zero
     # survivors, full stop.
     $survivors = @()
   } else {
     $escapedWorktree = [System.Management.Automation.WildcardPattern]::Escape($env:AAD_WORKTREE)
     $allProcs = Get-CimInstance Win32_Process
     $parentOf = @{}
     foreach ($p in $allProcs) { $parentOf[$p.ProcessId] = $p.ParentProcessId }
     # Precompute the orchestrator's own ancestor chain ONCE (walk up from
     # $PID through $parentOf) so the per-candidate check below can also
     # catch the reverse case: a candidate that is itself an ANCESTOR of the
     # orchestrator (e.g. a wrapper/launcher shell that spawned this process
     # and also happens to match the worktree-path substring via its own
     # cwd or invocation text). The plain upward walk from a candidate alone
     # (in Test-SelfAncestorOrDescendant below) can only ever detect the
     # candidate being $PID itself or a DESCENDANT of $PID — it can never
     # reach an ancestor of $PID, since ancestors lie in the opposite
     # direction of that walk.
     $orchestratorAncestorPids = @{}
     $walkPid = $PID
     for ($i = 0; $i -lt $allProcs.Count; $i++) {
       if (-not $parentOf.ContainsKey($walkPid)) { break }
       $walkPid = $parentOf[$walkPid]
       $orchestratorAncestorPids[$walkPid] = $true
     }
     function Test-SelfAncestorOrDescendant($candidatePid) {
       # Self/ancestor/descendant PID exclusion (ticket #86), walked per
       # candidate from the candidate's own PID upward through $parentOf —
       # never a pre-match snapshot subtraction, so a subshell/helper this
       # matcher's own pipeline forks after $allProcs was captured is still
       # correctly excluded, because the walk starts from that candidate's
       # own, already-existing PID rather than from a stale forward-computed
       # descendant tree. This covers self ($candidatePid -eq $PID) and any
       # DESCENDANT of the orchestrator. The reverse case — $candidatePid is
       # itself an ANCESTOR of the orchestrator — is covered separately
       # below via membership in the precomputed $orchestratorAncestorPids
       # set, since this upward-only walk can never reach it.
       $walkPid = $candidatePid
       for ($i = 0; $i -lt $allProcs.Count; $i++) {
         if ($walkPid -eq $PID) { return $true }
         if (-not $parentOf.ContainsKey($walkPid)) { return $false }
         $walkPid = $parentOf[$walkPid]
       }
       return $false
     }
     $rawMatches = $allProcs | Where-Object { $_.CommandLine -like "*$escapedWorktree*" }
     $survivors = $rawMatches | Where-Object {
       (-not (Test-SelfAncestorOrDescendant $_.ProcessId)) -and
       (-not $orchestratorAncestorPids.ContainsKey($_.ProcessId))
     }
   }
   ```
   `$survivors` is B2-match's output, consumed directly by B2-kill's own
   exe-name/broker filtering step below — B2-match itself deliberately does
   no exe-name filtering, since a legitimately-alive worker process can run
   under any executable name, not just the five named below.

   **B2-kill, Windows/PowerShell** — a separate, subsequent stage that takes
   `$survivors` and applies the exe-name allowlist + `app-server-broker.mjs`
   filter *before* killing, mirroring how POSIX below applies its own
   filtering only at the kill step, never inside B2-match:
   ```powershell
   $survivors |
     Where-Object {
       $_.Name -in @('node.exe', 'uvx.exe', 'uv.exe', 'serena.exe', 'python.exe') -or
       $_.CommandLine -like '*app-server-broker.mjs*'
     } |
     ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   ```

   The directory-lock failure is Windows-specific (POSIX lets `git worktree remove`
   unlink a directory with an open handle), but killing orphans is good hygiene
   everywhere.

   **B2-match, POSIX** — replaces the old unfiltered by-path kill
   sweep entirely, wrapped in a real `if`/`else` short-circuit — not a
   fragment that merely assigns an empty result and then keeps running the
   match unconditionally:
   ```sh
   if [ -z "$AAD_WORKTREE" ]; then
     # Fail-safe: an empty/unset AAD_WORKTREE must never fall through to
     # `pgrep -f ""`/`pgrep -f "$AAD_WORKTREE"` with an empty pattern, which
     # would match every process on the system. Zero survivors, full stop —
     # and pgrep never runs in this arm.
     survivors=""
   else
     escaped_worktree=$(printf '%s' "$AAD_WORKTREE" | sed -e 's/\\/\\\\/g' -e 's/[].[*^$(){}?+|]/\\&/g')
     candidates=$(pgrep -f "$escaped_worktree" || true)
     survivors=""
     # Precompute the orchestrator's own ancestor chain ONCE (walk up from
     # $$ through get_ppid) so the per-candidate loop below can also catch
     # the reverse case: a candidate that is itself an ANCESTOR of the
     # orchestrator (e.g. a wrapper/launcher shell that spawned this
     # process and also happens to match the worktree-path substring via
     # its own cwd or invocation text). The plain upward walk from a
     # candidate alone (the self/ancestor/descendant check below) can only
     # ever detect the candidate being $$ itself or a DESCENDANT of $$ — it
     # can never reach an ancestor of $$, since ancestors lie in the
     # opposite direction of that walk.
     orchestrator_ancestor_pids=""
     walk_pid=$(get_ppid "$$")
     while [ -n "$walk_pid" ]; do
       orchestrator_ancestor_pids="$orchestrator_ancestor_pids $walk_pid"
       walk_pid=$(get_ppid "$walk_pid")
     done
     for candidate_pid in $candidates; do
       # Self/ancestor/descendant PID exclusion (ticket #86), walked per
       # candidate from the candidate's own PID upward through the
       # pid->ppid map below — never a pre-match snapshot subtraction, so a
       # subshell this same pgrep pipeline forks (e.g. the command
       # substitution above) is still correctly excluded, because the walk
       # starts from that candidate's own, already-existing PID rather than
       # from a stale forward-computed descendant tree. This covers self
       # and any DESCENDANT of the orchestrator. The reverse case —
       # candidate_pid is itself an ANCESTOR of the orchestrator — is
       # covered separately below via membership in the precomputed
       # $orchestrator_ancestor_pids set, since this upward-only walk can
       # never reach it.
       walk_pid=$candidate_pid
       is_self_or_ancestor=false
       while [ -n "$walk_pid" ]; do
         if [ "$walk_pid" = "$$" ]; then
           is_self_or_ancestor=true
           break
         fi
         walk_pid=$(get_ppid "$walk_pid")  # /proc/*/stat primary; ps -eo pid,ppid fallback
       done
       case " $orchestrator_ancestor_pids " in
         *" $candidate_pid "*) is_self_or_ancestor=true ;;
       esac
       [ "$is_self_or_ancestor" = false ] && survivors="$survivors $candidate_pid"
     done
   fi
   ```
   `get_ppid` sources the same pid→`ppid` linkage B2-match's own descendant
   discovery already uses — a primary/fast path and a portable fallback: on
   Linux, a forward walk over `/proc/*/stat` (fast, reading each process's
   `ppid` from its stat entry); where `/proc` is unavailable (macOS/BSD), a
   walk over `ps -eo pid,ppid` output instead. This keeps the
   self/ancestor/descendant exclusion genuinely platform-independent, not
   Linux-`/proc`-only.

   **Regex-escaping (ticket #86).** `pgrep -f` interprets
   its argument as an **extended regular expression (ERE)**, not a literal
   substring. A worktree path containing an ERE metacharacter — `.`, `[`,
   `]`, `*`, `^`, `$`, `(`, `)`, `{`, `}`, `?`, `+`, `|`, or `\` — can
   overmatch unrelated processes whose command line happens to satisfy the
   resulting regex, or fail to match the intended worktree's own processes.
   Regex-escape `$AAD_WORKTREE` before it is ever passed to `pgrep -f`
   (verified against `grep -E`, which uses the same ERE engine class): first
   escape literal backslashes, then escape the remaining ERE metacharacters
   (`]` placed first inside the bracket expression so it is read as a
   literal character, not the closing bracket), exactly as shown in the
   `escaped_worktree=$(printf '%s' "$AAD_WORKTREE" | sed …)` assignment
   above.
   Only when `$AAD_WORKTREE` is non-empty: compute `$escaped_worktree` as
   above, then enumerate candidates via `pgrep -f "$escaped_worktree"`,
   unioned on Linux with a `/proc/<pid>/cwd` boundary-match against
   `$AAD_WORKTREE` (readlink each `/proc/[0-9]*/cwd` and keep the ones
   **equal to** `$AAD_WORKTREE`, **or** prefixed by `$AAD_WORKTREE` followed
   by a path separator — a bare prefix match would wrongly pull in a
   sibling worktree whose path merely starts with this one's, e.g. a
   worktree ending `...-575f0fcb` prefix-matching `...-575f0fcb-retry`, the
   exact retry-suffix naming this plugin's own B3 fallback recommends on a
   branch-name collision; this half is a literal path-boundary comparison,
   not a regex, so it needs no escaping), falling back to
   `pgrep -f "$escaped_worktree"` alone where `/proc` is unavailable
   (macOS/BSD); then apply the per-candidate self/ancestor/descendant
   exclusion walk above. This produces the same broad, unfiltered survivor
   set as Windows's B2-match above — path matching and self/ancestor/
   descendant exclusion only, **no exe-name filtering** at this stage. This
   unfiltered survivor set is consumed directly by B2-kill's own exe-name/
   broker filtering step below — B2-match itself deliberately does no
   exe-name filtering, because a legitimately-alive worker process can run
   under any executable name, not just the five named below. The
   `/proc/<pid>/cwd` boundary fix above only closes this residual for the
   cwd half of the match; the command-line half (`pgrep -f`/`-like`
   substring matching) can't do better than substring matching and keeps the
   same residual.

   **Accepted tradeoff — out of scope for ticket #86 (broad-by-design
   matching).** B2-match's survivor set is intentionally broad: it matches
   *any* process whose command line or cwd references the worktree path, not
   only a `process-ticket` worker process (e.g. a user's editor or shell left
   open on that folder also matches). B2-kill's exe-name/broker filtering
   step (immediately below) narrows this before anything is actually killed
   — the broad, unfiltered survivor set above is never killed directly. This
   is a pre-existing property of the broad-matching design that predates and
   is unrelated to ticket #86's self-match fix — accepted as-is, explicitly
   out of scope here.

   **B2-kill, POSIX** — a separate, subsequent stage that takes B2-match's
   survivor set and applies the exe-name allowlist + `app-server-broker.mjs`
   filter *before* killing, mirroring Windows's B2-kill above — the raw,
   unfiltered survivor set is never killed directly: for each survivor PID,
   inspect its command name/args (`ps -o comm=,args= -p <pid>`) and keep it
   only if `comm` matches the POSIX equivalents of the Windows exe-name
   allowlist — `node`, `uvx`, `uv`, `serena`, `python` (the same five names,
   without the `.exe` suffix, matched against the command basename) — or
   `args` contains `app-server-broker.mjs`. Only *that filtered subset* gets
   `kill -TERM`, then a brief in-shell grace (e.g. a plain `sleep 2` — this
   is a short, local teardown pause, **not** a long-running foreground wait;
   this skill never blocks a turn on a long foreground wait, per the
   full-suite integration-gate step's `nohup`+`Monitor` pattern, but a
   two-second teardown grace like this one is a different, short-lived thing
   entirely) followed by a `kill -0 <pid>` liveness recheck on
   that same filtered subset, and only the PIDs the recheck still finds
   alive get `kill -KILL` (not a blind re-sweep of the full filtered subset,
   let alone the raw unfiltered survivor set) — broad enough to catch the
   broker or the Serena LSP chain, but no longer broad enough to kill a
   user-launched editor or shell that merely happens to be pointed at the
   worktree path. Caveat: B2-match
   itself is still intentionally broad — it still matches **any** *other*
   process whose command line references the worktree path, not just the
   Codex broker/Serena LSP chain, which is exactly why B2-kill's filtering
   step above exists and must never be skipped; what's new is that the
   orchestrator's own process tree is excluded by construction from
   B2-match's survivor set. Dispatch is sequential now (ticket #88), so
   B2-match's teardown sweep only ever targets one worktree path per
   invocation — there is no concurrent-across-members case for it to
   disambiguate.
2. **Confirm the directory is free**, then remove the worktree via the
   agent-worktree MCP (`worktree_remove`) so it releases ports, runs teardown,
   and updates its state store. Do not `rm -rf` the directory or run
   `git worktree remove` by hand — that desyncs the MCP's state.
3. **Self-cwd-lock terminal case (Windows-specific, distinct from B2) — detect
   and flag, do not loop.** If B2's path-matched sweep found **zero**
   processes, and the first `force=true` `worktree_remove` attempt from step 2
   still reports the literal signature
   `"directory is still locked after killing 0 blocking process(es)"`
   or a raw `Permission denied` on an otherwise-empty directory, this is
   **not** a foreign-process case — B2 already came back empty, so there is
   no PID left to find or kill. The blocker is the orchestrator's **own
   background-job shell**, whose cwd silently sits inside the worktree being
   torn down (the same cwd-drift mechanism #66 fixed for git invocations —
   see AGENTS.md's cwd-independent-git invariant). On this signature:
   - **Do not loop** the B2 kill logic — re-running the sweep will keep
     finding zero processes forever, since the holder isn't a foreign PID.
   - **Do not attempt a `cd`/`Set-Location` away** from the directory to free
     it — cwd control from within the shell holding the lock is unreliable
     (per #66).
   - Instead, **record the worktree path on a run-level
     `manual-cleanup-needed` list** and move on — teardown is routine hygiene
     and, like the rest of this section, does not gate run correctness.
     Surface that list to the user in Phase D step 3 so stale directories are
     always flagged, never silently accumulated.

**Recovery — already-desynced phantom entry.** If a worktree was left desynced
(git no longer lists it, the directory persists, and the MCP still shows
`status: created`), `worktree_remove` — even with `force=true` — fails with
`fatal: '<path>' is not a working tree`. Recover by hand: kill any lingering
process per B2 above → remove the directory
(`Remove-Item -Recurse -Force '<worktree-path>'`) → delete the merged local
branch (`git -C <repo_root> branch -d <branch>`). The phantom MCP entry then
remains —
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
- **Sequential, not parallel, throughout Phase C.** Worktree creation within a
  wave is serialized (git index lock races), and — as of ticket #88 —
  driving `process-ticket` for each wave member is sequential too, one fresh
  unnamed dispatch at a time, never parallel/named spawns. Only the wave's
  *worktrees* are set up ahead of a member's own dispatch (step 1); nothing
  in this skill runs two wave members' pipelines concurrently.
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
  `worktree_remove` → **if still locked/Permission-denied with zero foreign
  PIDs found by B2, that's the self-cwd-lock terminal case: flag the path on
  the `manual-cleanup-needed` list, don't loop the B2 kill logic, and don't
  try to cd away.** These are plain helper processes — force-killing them is
  correct and safe.
- **Merge criterion comes directly from the report — no self-report-loss
  fallback needed (ticket #88).** Because Phase C step 2 dispatches wave
  members sequentially and unnamed, one at a time, the orchestrator always
  gets each member's real, complete ending state — `VERDICT: APPROVE`/
  `CHANGES_REQUESTED` and test `PASS`/`FAIL` — directly from that member's
  own synchronous Phase-4 report; there is never a dropped-report gap to
  compensate for, so no git-state/marker-file fallback and no separate
  liveness-disambiguation step are needed here any more. A member is merged
  only when its report shows `APPROVE` **and** `PASS`; anything else is not
  merged and rolls into a later wave. See Phase C step 2 for the full
  rationale.
- **Backlog release gate (implicit "none"/"all open" MULTI path only).**
  Before spawning the analyst on that path, `list_board_columns` detects a
  literal `Backlog` column and, whenever a board is configured, also detects
  tickets never triaged onto the board (no board Status/column value set);
  it filters open tickets sitting in `Backlog` and untriaged tickets alike
  out of the candidate set (zero-survivors STOPs before the spawn); SINGLE
  mode and an explicit MULTI subset ("several") bypass it entirely, and
  skipped tickets (Backlog-column or untriaged) surface only as a
  display-only Phase B group, never merged into `deferred`.
- **Phase B confirmation defaults to skipped on a clean run.** A clean run
  (SINGLE mode, or MULTI with `fit.verdict == "good"` AND `deferred` empty)
  proceeds without the interactive AskUserQuestion gate by default — no flag,
  no persisted preference, no opt-back-in. The two mandatory cases
  (`fit.verdict == "poor"`, or a non-empty `deferred` list) are never skipped
  — the interactive gate always runs for those. Even when the gate is
  skipped, a plain, non-interactive status message listing the waves (in
  order, with branches) is still printed, so an attended user always sees
  the plan.
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
