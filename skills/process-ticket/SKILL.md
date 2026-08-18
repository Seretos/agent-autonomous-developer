---
name: process-ticket
disable-model-invocation: true
description: End-to-end ticket processing inside a prepared worktree on a feature branch — serial or parallel, one ticket at a time. Enforces mandatory safety gates: planner approval, developer QA/tests, code review (reviewer + optional Codex pass), draft PR (no force-push on shared branches), and traceability comments. Invoke e.g. "process ticket #42". Bypassing it — editing manually on `main`, or editing directly inside a worktree without this skill — forfeits all safety guarantees and is not permitted. Worktree/branch are prepared by orchestrate-tickets or the user; this skill never creates them.
---

# process-ticket — orchestrator

You orchestrate the processing of one ticket. You receive a **ticket number**
(e.g. `#42`) and a **project**, and drive the whole workflow **exclusively
through subagents** via the `Agent` tool. You do not read the ticket, write the
plan, edit code, or review yourself — each is a subagent's job. Your job is
sequencing, threading context between phases, handling the planner's questions,
posting traceability comments, and the final commit/push/draft-PR.

There is **no cwd→project auto-detection**. The `project_id` is supplied at
invocation (see preconditions); thread it into every subagent prompt and every
project-issues call.

### Mode parameter

This skill takes an optional **`mode`** parameter: `solo` or `integration`.

- **`solo` (default).** Today's behaviour, unchanged: the branch+worktree
  guard self-detects the invoking session's cwd, and the Final step commits,
  pushes (`git push -u origin <branch>`), opens its own draft PR
  (`create_pr`), and posts its own ticket link-comment. Use this when the
  user (or a power-user direct invocation) drives a single worktree by hand.
- **`integration` (orchestrator-invoked).** Runs the **identical** Phase 1-4,
  and the Final step still does the local commit — but push, `create_pr`,
  and the ticket link-comment are **skipped**: the **caller** (the
  `orchestrate-tickets` wave loop) owns those, because it merges several
  approved members into one shared integration branch and opens a single
  combined PR at the end of the run. In this mode the caller supplies an
  explicit **`worktree_path`** (and branch name) so the branch+worktree guard
  can validate the right directory instead of self-detecting cwd — see
  Preconditions 2. If `mode=integration` is given with no `worktree_path`,
  **STOP**.

The commit step runs in **both modes**; push/create_pr/the ticket comment run
**ONLY in `solo` mode**; the final report-to-caller step runs in both modes
(adjusted wording — see Final step). The never-on-main invariant (branch
guard STOP on `main`/`master`) is **not relaxed** in either mode — it is
still checked, unconditionally, in both.

### Mandatory safety gates (apply to every ticket — serial or parallel)

This skill is the required processing path whether the ticket is a single
serial/foundational change or one of a parallel fleet. Running a ticket
manually on `main` — editing files directly, committing inline, or
force-pushing — bypasses all of the following guarantees and is **not
permitted**. The same applies if the orchestrator session enters a worktree
and edits files directly — bypassing this skill in a worker's directory is
identical in effect. Building or running the project locally from the main
checkout to *verify* behaviour (without editing) is not a bypass; *editing* is.

1. **Planner approval gate.** The planner subagent produces a plan and answers
   the user's questions before any code is written; the plan is posted as a
   ticket comment for traceability.
2. **Developer QA / tests.** The developer runs the project's test suite —
   the full suite backgrounded via `nohup … > <log> 2>&1 &` plus an in-turn
   `Monitor` wait, never a plain foreground call subject to the tool's
   ~10-minute timeout — and must report PASS before the workflow continues;
   unfixable failures stop the pipeline. A developer or reviewer may instead
   return a **blocked/in-progress** status report (e.g. it is still waiting
   on its own backgrounded command and is handing ownership of that wait to
   this skill) — see Phase 3 below for how that return is handled.
3. **Code review — reviewer subagent + optional Codex pass.** The reviewer
   reads the diff and returns `APPROVE` or `CHANGES_REQUESTED`; blocking
   findings trigger one fix cycle. When the Codex plugin is active, a Codex
   correctness pass is folded into the verdict automatically.
4. **Draft PR, no force-push on shared branches.** The feature branch is
   pushed and the PR opened as a draft; the user finalizes and merges. Direct
   commits to `main` or force-pushes to shared branches are never performed.
5. **Traceability comments.** The short-form plan and the PR link are posted
   back to the ticket so every change is auditable.

## Preconditions / guards (before anything else)

1. **Confirm the ticket number and the project.** The invocation carries a
   ticket number and a project id (e.g. `process ticket #42 in acme-api`). If
   the ticket number is missing, ask. If the project id is missing or unclear,
   resolve it via `find_projects` and confirm with the user — never guess.
   Capture `project_id` for every downstream call.
2. **Branch + worktree guard.** This guard is now defense-in-depth; the dispatcher normally ensures the correct skill is loaded before reaching this point. This skill runs **only inside a worktree** on a
   feature branch — it is the worker half of `orchestrate-tickets` (which runs
   only on the main checkout). The check target depends on `mode`:
   - **`solo` mode (default):** checks run against the invoking session's own
     cwd, unchanged:
     - `git rev-parse --abbrev-ref HEAD` — if `main`/`master`, STOP.
     - `git rev-parse --git-dir` vs `git rev-parse --git-common-dir` — if they
       are EQUAL you're in the main checkout, not a worktree → STOP.
   - **`integration` mode:** the orchestrator passes an explicit
     `worktree_path` and branch name. If `mode=integration` but no
     `worktree_path` was supplied, **STOP** — do not guess a directory. When
     it is supplied, run the same two checks against that path instead of
     self-detecting cwd:
     - `git -C <worktree_path> rev-parse --abbrev-ref HEAD` — if
       `main`/`master`, STOP. This invariant is **not relaxed** for
       integration mode — still STOP.
     - `git -C <worktree_path> rev-parse --git-dir` vs
       `git -C <worktree_path> rev-parse --git-common-dir` — if EQUAL, STOP.
   On STOP, tell the user (or the caller, in integration mode) this skill must
   run inside a prepared feature-branch worktree, which the user (or
   orchestrate-tickets) owns. Do not create a branch or worktree yourself.
   Capture the branch name and the default branch (for the PR base).

## Phase sequence

Each subagent is a leaf (no further delegation) and cannot refetch context
it wasn't given. Thread each phase's output into the next phase's prompt.

### Board card movement (ticket #77)

As this skill drives each phase, it best-effort moves the ticket's board card
to reflect pipeline state — the write side of sibling ticket #76's read/
filter-only "Backlog release gate." Gated on the same board-detection
mechanism #76 introduced: `list_board_columns(project_id)` (exact/full-token
column-name match, not substring — mirrors #76's own matching convention). No
board configured, or no board column literally matching the target phase's
name, means the specific write is skipped silently — same backward-compat
semantics as #76's read-side gate.

**Phase → column mapping:**
- **Phase 1** (context-extractor + planner begin) → move the card to
  `Doing`: `update_ticket(project_id=<project>, ticket_id=<#>,
  custom_fields={"Status": "Doing"})`.
- **Phase 4** (reviewer invoked) → move the card to `Review`:
  `update_ticket(project_id=<project>, ticket_id=<#>,
  custom_fields={"Status": "Review"})`.
- **Fix loop** (`CHANGES_REQUESTED` re-dispatch) → move the card back to
  `Doing` before the developer re-dispatch, then to `Review` again once the
  re-review runs.

**Best-effort, never blocking.** This is intentionally looser than #76's
read-side STOP-on-ambiguous-error behavior — state the contrast explicitly so
it is not "hardened" into a blocker later. ANY failure here — a
`list_board_columns` detection error, no target column matching, or a failed
`update_ticket` call — degrades to a logged warning and the pipeline
continues; a board-write failure must never STOP or block the ticket's real
work.

**Provider-agnostic.** This mapping relies solely on `list_board_columns` and
`update_ticket`, which already normalize the underlying board/column model
for the connected provider — never hardcode provider-specific column
semantics here.

**Review is terminal automated state — no automated `Done` write anywhere.**
Phase 4's move to `Review` is the LAST board write this skill ever makes for
a ticket, in both `solo` and `integration` mode. The Final step below adds no
completion/terminal board write in either mode — deliberate: only a human (or
the real PR-merge event) later transitions the card to `Done`.

### Phase 1 — context-extractor (read-only)
Spawn `context-extractor`. Pass: the `project_id` and the ticket number. It
returns a distilled **context_summary** (problem, acceptance criteria,
constraints from comments, related tickets/PRs, candidate affected modules).
Capture it verbatim — downstream agents never see the raw ticket.

**Board card movement.** At the start of this phase (context-extractor +
planner begin), gated on `list_board_columns` per the Board card movement
subsection above, move the ticket's board card to `Doing` via `update_ticket`.

If the context-extractor is blocked by the MCP-availability hook (i.e. the
`agent-project-issues` MCP was not loaded), `process-ticket` will receive no
`context_summary`. In that case, surface the hook's failure reason to the user
and stop — do not attempt Phase 2 with an empty or missing summary.

### Phase 2 — planner (read-only, question-loop)
Spawn the planner **synchronously and unnamed**:
`Agent(subagent_type="planner", prompt=…, run_in_background: false)`. Pass
the `context_summary` and the repo cwd.

Do not pass a `name`. Naming this call switches it into background/mailbox
delivery regardless of `run_in_background`, and the planner has no
`SendMessage` tool to push a reply back once it's in that mode — the
orchestrator then only ever receives `idle_notification` pings and Phase 2
deadlocks permanently. Always use a plain, unnamed, foreground call.

The planner ends every reply with a status line as its LAST line:
- `STATUS: PLAN_FINAL` — no open questions.
- `STATUS: NEEDS_INPUT` — reply contains a numbered `## Open Questions`
  section (each question 2-4 options, one marked *(recommended)*).

Loop:
1. Read the status line of the synchronous reply.
2. `PLAN_FINAL` → capture full plan text as `plan`, exit loop.
3. `NEEDS_INPUT` → present each open question to the user via
   **AskUserQuestion** (options from the planner, recommended flagged).
   Collect answers, then issue a **fresh synchronous planner call** (same
   unnamed, `run_in_background: false` pattern as above) whose prompt
   inlines: the `context_summary`, the repo cwd, the planner's full previous
   plan draft **verbatim**, and the user's answers keyed to question numbers
   — with the explicit instruction to fold the answers into that same plan
   and revise, not start over. Back to step 1.

Each round is a brand-new subagent process with no memory of the previous
one — continuity comes from the orchestrator re-inlining the full plan draft
into every follow-up prompt, not from any runtime session. If `NEEDS_INPUT`
recurs more than ~4 times, surface it and ask whether to proceed with the
recommended defaults.

This same class of bug can also surface one level up: when `orchestrate-tickets`
drives several wave members in parallel, each member is necessarily a
background/named `Agent` spawn (required to run concurrently), and that
spawn's mailbox delivery can just as silently drop a worker's final
report-back. See AGENTS.md's **B6** note and
`skills/orchestrate-tickets/SKILL.md`'s Phase C idle-triggered fallback for
how that worker-level analogue is handled — unlike here, the fix there is a
fallback, not elimination of named spawns, because Phase C's members must run
in parallel.

The same class of bug also recurs a third time, *within this pipeline*, at
the Phase 3/4 fix loop: re-dispatching the developer or re-running the
reviewer by resuming the same, already-spawned agent via `SendMessage` is
inherently background/mailbox delivery too, regardless of how the original
spawn was made — see Phase 4's fix-loop bullet below. It is resolved the same
way as Phase 2: every fix-loop re-dispatch is a fresh, synchronous, unnamed
`Agent()` call, never a `SendMessage` resume of the prior spawn. Keep this in
mind before reintroducing a fourth instance of the bug elsewhere in the
pipeline.

**After PLAN_FINAL — post short plan comment.** Condense `plan` to a
short-form summary (goal + approach bullets + affected files; NOT every
detail) and post it to the ticket via
`add_comment(project_id=<project>, ticket_id=<#>, body=…)`.
Do not type `#ai-generated` — the MCP prepends it.

### Phase 3 — developer (Edit / Write / Bash)
Spawn the developer **synchronously and unnamed**, mirroring Phase 2:
`Agent(subagent_type="developer", prompt=…, run_in_background: false)`. Pass
the full `plan` and the `context_summary`. It implements on the **current
branch/worktree**, edits/writes files, and runs the project's test suite (the
test command is auto-detected from the stack and named in the plan; the full
suite runs backgrounded via `nohup … > <log> 2>&1 &` plus an in-turn
`Monitor` wait, per `agents/developer.md`'s Hard Rules). It returns a
**change_report** (files touched, summary, test result PASS/FAIL with
failing test names). If it reports unfixable failing tests, STOP and report
to the user — do not push a broken branch.

**Blocked/in-progress report.** A `blocked`/`in-progress` return from the
developer (or, in Phase 4, the reviewer) is a legitimate result, not an
error: it means the sub-agent is still waiting on its own backgrounded
command and is handing ownership of that wait back to this skill instead of
ending its turn. Treat it as such — **surface it to the user**, and do
**not** treat it as a completed phase and do **not** proceed to commit on
the strength of it. The orchestrator then decides whether to re-poll (a
fresh, synchronous, unnamed re-dispatch, never a `SendMessage` resume — see
the deadlock note above) or stop and report the blocker.

Do not pass a `name`. Naming this call switches it into background/mailbox
delivery regardless of `run_in_background`, and the developer has no
`SendMessage` tool to push a reply back once it's in that mode — the
orchestrator then only ever receives `idle_notification` pings and Phase 3
deadlocks permanently. Always use a plain, unnamed, foreground call. This
applies to the initial spawn here **and** to every fix-loop re-dispatch in
Phase 4 below — see that section for why resuming this same spawn via
`SendMessage` is not a substitute.

### Phase 4 — reviewer (read-only)
Spawn the reviewer **synchronously and unnamed**, mirroring Phase 2 and
Phase 3: `Agent(subagent_type="reviewer", prompt=…, run_in_background:
false)`. Pass the final `plan` and the developer's `change_report`; instruct
it to review the working-tree diff (`git diff` / `git diff --staged`). It
returns `VERDICT: APPROVE` or `VERDICT: CHANGES_REQUESTED` plus
severity-tagged findings (`[blocking]` / `[nit]`).
(If the Codex plugin is active, the reviewer adds a Codex correctness pass on
its own — the verdict format and this fix loop are unchanged.)

Do not pass a `name` to this spawn either, for the same reason as Phase 3:
naming it switches delivery to background/mailbox regardless of
`run_in_background`, and the reviewer has no `SendMessage` tool to push a
reply back once it's in that mode.

**Board card movement.** When the reviewer is invoked for this phase, gated
on `list_board_columns` per the Board card movement subsection above, move
the ticket's board card to `Review` via `update_ticket`.

- `CHANGES_REQUESTED` with blocking findings → re-dispatch the developer and
  reviewer, **each as a brand-new, fresh, synchronous, unnamed `Agent(...)`
  call** — `Agent(subagent_type="developer", prompt=…, run_in_background:
  false)` with the findings appended to the plan, then, once it reports,
  `Agent(subagent_type="reviewer", prompt=…, run_in_background: false)` for a
  **full review** (correctness, test coverage, consistency, and — if the Codex
  plugin is active — the Codex correctness pass). Do not narrow the re-review
  prompt to only checking that prior blocking findings are resolved. As with
  Phase 2's question-loop, each round is a brand-new subagent process with no
  memory of the previous one — re-inline the plan (plus the findings) and the
  `change_report` into each fresh prompt for continuity.
  This re-dispatch is **never a `SendMessage` resume** of the prior developer
  or reviewer spawn: resuming an existing agent via `SendMessage` is
  *inherently* background/mailbox delivery regardless of how the original
  spawn was made, silently reintroducing the same idle-without-report gap on
  every fix-cycle iteration. Always issue a fresh foreground `Agent()` call
  instead. After one fix cycle, proceed and report any remaining
  non-blocking findings.
  **Board card movement:** before the developer re-dispatch, gated the same
  way, move the card back to `Doing`; then, once this re-review runs, move it
  to `Review` again.
- `APPROVE` → proceed to the final step.

## Final step — commit, push, open draft PR, comment (orchestrator does this)

The orchestrator owns this (not the developer): it depends on the whole
pipeline's outcome (final plan + review verdict) and the branch/ticket the
orchestrator holds, and it keeps the developer's tool scope minimal.

**Mode-gated.** Step 1 (the target-repo `.gitignore` guarantee) and Step 2
(commit) both run in **both** `solo` and `integration` mode — Step 1 runs
**first**, so its append (when needed) is folded into Step 2's `git add -A`
and becomes part of *this run's own commit*, correctly attributed. Steps 3-5
(push, create_pr, ticket comment) run **ONLY in `solo` mode** — in
`integration` mode the **caller** (the `orchestrate-tickets` wave loop) owns
the push, the merge into the shared integration branch, and the single
end-of-run combined PR + comments, so this skill skips them here. Step 6
(write the result-marker file) runs **unconditionally in both modes**. Step 7
(report) also runs in both modes, with adjusted wording for integration mode.

**No completion/terminal board write (either mode).** None of the steps below
write a completion/terminal board column in **`solo`** or **`integration`**
mode. Phase 4's move to `Review` (see the Board card movement subsection
above) is the last board write this skill ever makes for a ticket — this
Final step never moves the card to `Done` or any other terminal column.

1. **Target-repo `.gitignore` guarantee** (both modes — runs **before** the
   commit below, so any append lands inside this ticket's own commit rather
   than sitting uncommitted for a later, unrelated ticket to sweep up via its
   own `git add -A`). `process-ticket` always runs against an arbitrary
   **target project repo** supplied via `project_id`/`worktree_path`, never
   "this plugin repo itself" — see AGENTS.md's "Why the project id is always
   a parameter". This plugin's own `.gitignore` entry for
   `.process-ticket-result.json` therefore has **zero effect** on real usage:
   it only helps when testing this plugin against its own repo, and is not
   representative of how process-ticket is actually invoked. To make the
   marker actually safe in an arbitrary target repo, check the
   **target repo's own `.gitignore`**, not this plugin's:
   - Read `<target repo root>/.gitignore` (repo root for `solo` mode,
     `<worktree_path>` for `integration` mode) — treat a missing file as
     empty.
   - If it does not already contain the exact line
     `.process-ticket-result.json`, append that line as a new final line
     (creating the file if it doesn't exist yet). This is a one-line,
     idempotent, safe append: check first, and never touch, reorder, or
     rewrite any other line already in that file.
   - Because this check/append runs **before** step 2's `git add -A`, when an
     append is needed it is staged and committed as part of *this run's own*
     commit — properly attributed to the ticket that first needed it — rather
     than left as an uncommitted stray change for a later, unrelated ticket's
     `git add -A` to silently absorb.
   - **Persistence note (both modes).** Once the line is present, every
     subsequent `process-ticket` run against this same worktree/repo finds it
     already there and appends nothing further — by the time a later run
     reaches its own step 1, `.gitignore` already excludes the marker, so that
     later run's step 2 `git add -A` correctly skips the still-untracked,
     now-ignored marker file left over from this run. In `solo` mode no
     orchestrator ever reads the marker (only the `integration`-mode wave
     loop's fallback does), so no cleanup step is needed here.
2. **Commit** (raw git — no MCP for a local commit; both modes). The commit
   target depends on `mode`, mirroring the branch/worktree guard in
   Preconditions 2:
   - **`solo` mode:** commit against the invoking session's own cwd, unchanged
     — `git add -A`, then:
     - **Single-line message** (summary only, no body or trailers):
       `git commit -m "<concise summary> (#<ticket>)"`.
     - **Multi-line message** (body text, Co-Authored-By trailer, etc.): use
       the Write tool to write the full message to `/tmp/commit-msg.txt`, then
       run `git commit -F /tmp/commit-msg.txt`.
   - **`integration` mode:** the orchestrator's session cwd may be the main
     checkout, not the worktree, by the time this step runs — do **not** rely
     on cwd. Target the supplied `worktree_path` explicitly on every git call:
     - `git -C <worktree_path> add -A`, then:
     - **Single-line message:**
       `git -C <worktree_path> commit -m "<concise summary> (#<ticket>)"`.
     - **Multi-line message:** use the Write tool to write the full message to
       `/tmp/commit-msg.txt`, then run
       `git -C <worktree_path> commit -F /tmp/commit-msg.txt`.
   - In both modes, for a multi-line message, writing via the Write tool
     sidesteps shell quoting entirely — no heredoc, no escaping. Never compose
     a multi-line commit message as a PowerShell here-string (`@'...'@`) and
     run it through the Bash tool. The Bash tool executes real `bash`, not
     PowerShell — `@'...'@` delimiters have no meaning in bash and pass `@`
     literally as text, corrupting the commit subject line.
3. **Push** the feature branch (**`solo` mode only**):
   `git push -u origin <branch>`.
4. **Open the PR as a draft via MCP** (**`solo` mode only**; MCP over CLI per
   the priority law):
   `create_pr(project_id=<project>, title=<from plan>,
   head=<branch>, base=<default branch>, draft=True,
   body=<summary + "Closes #<ticket>" + plan recap + review verdict>)`.
   Never type `#ai-generated` — the MCP prepends it.
   (`Closes #<n>` auto-links on GitHub/GitLab; if the project's provider is
   Azure DevOps or Jira this keyword differs — adjust if you ever target those.)
5. **Comment on the ticket** linking the PR (**`solo` mode only**):
   `add_comment(project_id=<project>, ticket_id=<#>,
   body="Draft PR opened: <PR URL>. <one-line status>")`.
6. **Write a result-marker file** (raw `Write` tool — **unconditional, in
   both modes**, not mode-gated). This step exists so a caller can recover
   this run's ending state even if step 7's report never arrives (e.g. a
   parallel `orchestrate-tickets` wave-member spawn that goes idle without
   replying — see AGENTS.md's **B6** note and
   `skills/orchestrate-tickets/SKILL.md`'s Phase C fallback, which reads this
   exact file). Write it **after** the commit (step 2) — `git add -A` has
   already run by then, so the marker is never staged into the ticket's own
   diff. By this point step 1 has already ensured the target repo's
   `.gitignore` contains the marker's line, so this newly-written marker file
   is untracked-and-ignored from the moment it's written, not merely
   untracked:
   - **`solo` mode:** write to `<repo root, resolved via `git rev-parse
     --show-toplevel` from the invoking session's own cwd>/.process-ticket-result.json`.
   - **`integration` mode:** write to `<worktree_path>/.process-ticket-result.json`
     (the caller-supplied path, same as the commit step). Unconditional, both
     modes.
   - **Contents (JSON object):**
     ```json
     {
       "ticket": <ticket number>,
       "branch": "<branch>",
       "verdict": "APPROVE",
       "test": "PASS",
       "mode": "integration"
     }
     ```
     `verdict` is one of `APPROVE` / `CHANGES_REQUESTED` (the reviewer's final
     verdict); `test` is one of `PASS` / `FAIL` (the developer's final test
     result); `mode` is `solo` or `integration`, whichever this run used.
     `ticket` is this run's own ticket number — a downstream reader (see
     AGENTS.md's **B6** note) must treat a `ticket` value that doesn't match
     the run it thinks it's confirming as untrustworthy, since a worktree
     left intact after a RED wave (no auto-revert) could in principle carry a
     stale marker from an earlier attempt. This write itself is unconditional
     in both modes — only the `mode` field's *value* varies.
   - **Persistence note (both modes).** This file is expected to persist in
     the worktree afterward as a harmless untracked, gitignored artifact (see
     step 1's guarantee, not this plugin's own `.gitignore`) — in `solo` mode
     no orchestrator ever reads it (only the `integration`-mode wave loop's
     fallback does), so no cleanup step is needed here.
7. **Report back:**
   - **`solo` mode:** report to the user — PR URL, branch, review verdict,
     test result, and `final: true`.
   - **`integration` mode:** report to the caller (the orchestrator) instead
     of the user — branch, review verdict, test result, `final: true`, and
     the local commit is ready for the caller to merge. No PR URL exists yet
     at this point; the caller opens the single combined PR at the end of
     the run.
   - **`final: true`** is an explicit terminal-marker field carried by the
     report message itself — distinct from the `.process-ticket-result.json`
     marker *file* (step 6 above), which already carries
     ticket/branch/verdict/test/mode. It marks this report as the definitive
     terminal signal a caller keys its confirmed-done-set entry on (see
     AGENTS.md's **B6** note). Required in **both** modes for a single
     uniform report contract, even though in `solo` mode no orchestrator
     ever reads it.

## Hard rules
- **Delegate everything.** Never call `get_ticket`, `Edit`/`Write`, or review
  a diff yourself. Your tools: `Agent`/`SendMessage`, `AskUserQuestion`, the
  branch-guard git reads, the final commit/push git calls, and the
  project-issues write calls (`add_comment`, `create_pr`, `update_ticket`,
  `list_board_columns` — the last two for the best-effort board card
  movement writes, see the Board card movement subsection above).
- **Project id is a parameter.** Thread the supplied `project_id` into every
  subagent prompt and MCP call — never hardcode a project.
- **Subagents can't refetch.** Inline the summary/plan into each prompt.
- **Never run on main.** Enforce the branch guard up front.
- **Never create the worktree/branch.** The user owns that.
- **Push is authorized for this workflow only** (user-confirmed). PR opens as
  a **draft** so the user finalizes it.
- **Multi-line commit messages must use `git commit -F <tempfile>` — never
  `@'...'@` via the Bash tool.** The Bash tool runs real `bash`, not
  PowerShell. A PowerShell here-string (`@'...'@`) passed to the Bash tool
  produces `@` as the commit subject, corrupting the message. For any message
  with a body or trailers, use the Write tool to write it to a well-known temp
  path (e.g. `/tmp/commit-msg.txt`) and commit with `git commit -F
  <tempfile>`. The single-line `-m` form remains correct for summary-only
  messages.
- **`integration` mode's commit must target `-C <worktree_path>` explicitly —
  never a bare `git add`/`git commit` relying on cwd.** The orchestrator's
  session cwd is not pinned to the worktree the way a `solo`-mode invoking
  session's cwd is, so a bare `git commit` in integration mode risks landing
  in the wrong repository/branch. This mirrors the branch/worktree guard's own
  `-C <worktree_path>` fix in Preconditions 2 — same assumption, same fix,
  applied at the point where files actually get committed.
