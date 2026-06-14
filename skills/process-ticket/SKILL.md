---
name: process-ticket
description: End-to-end ticket processing inside a prepared worktree on a feature branch — serial or parallel, one ticket at a time. Enforces mandatory safety gates: planner approval gate, developer QA/tests, code review (reviewer subagent + optional Codex pass), draft PR (no force-push on shared branches), and traceability comments. Invoke e.g. "process ticket #42 in acme-api". Bypassing this skill — editing manually on main — forfeits all safety guarantees and is not permitted. Worktree and branch are prepared by orchestrate-tickets (or the user); this skill never creates them.
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

### Mandatory safety gates (apply to every ticket — serial or parallel)

This skill is the required processing path whether the ticket is a single
serial/foundational change or one of a parallel fleet. Running a ticket
manually on `main` — editing files directly, committing inline, or
force-pushing — bypasses all of the following guarantees and is **not
permitted**:

1. **Planner approval gate.** The planner subagent produces a plan and answers
   the user's questions before any code is written; the plan is posted as a
   ticket comment for traceability.
2. **Developer QA / tests.** The developer runs the project's test suite and
   must report PASS before the workflow continues; unfixable failures stop the
   pipeline.
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
2. **Branch + worktree guard.** This skill runs **only inside a worktree** on a
   feature branch — it is the worker half of `orchestrate-tickets` (which runs
   only on the main checkout). Two checks:
   - `git rev-parse --abbrev-ref HEAD` — if `main`/`master`, STOP.
   - `git rev-parse --git-dir` vs `git rev-parse --git-common-dir` — if they are
     EQUAL you're in the main checkout, not a worktree → STOP.
   On STOP, tell the user this skill must run inside a prepared feature-branch
   worktree, which the user (or orchestrate-tickets) owns. Do not create a branch
   or worktree yourself. Capture the branch name and the default branch (for the
   PR base).

## Phase sequence

Each subagent is a leaf (no further delegation) and cannot refetch context
it wasn't given. Thread each phase's output into the next phase's prompt.

### Phase 1 — context-extractor (read-only)
Spawn `context-extractor`. Pass: the `project_id` and the ticket number. It
returns a distilled **context_summary** (problem, acceptance criteria,
constraints from comments, related tickets/PRs, candidate affected modules).
Capture it verbatim — downstream agents never see the raw ticket.

If the context-extractor is blocked by the MCP-availability hook (i.e. the
`agent-project-issues` MCP was not loaded), `process-ticket` will receive no
`context_summary`. In that case, surface the hook's failure reason to the user
and stop — do not attempt Phase 2 with an empty or missing summary.

### Phase 2 — planner (read-only, question-loop)
Spawn the planner **with a name** so you can resume it:
`Agent(name="planner-<ticket>", subagent_type="planner", prompt=…)`. Pass the
`context_summary` and the repo cwd.

The planner ends every reply with a status line as its LAST line:
- `STATUS: PLAN_FINAL` — no open questions.
- `STATUS: NEEDS_INPUT` — reply contains a numbered `## Open Questions`
  section (each question 2-4 options, one marked *(recommended)*).

Loop:
1. Read the status line.
2. `PLAN_FINAL` → capture full plan text as `plan`, exit loop.
3. `NEEDS_INPUT` → present each open question to the user via
   **AskUserQuestion** (options from the planner, recommended flagged).
   Collect answers, then **resume the same agent** with
   `SendMessage(name="planner-<ticket>", …)` carrying the answers keyed to
   question numbers. Back to step 1.

Never re-spawn a fresh planner inside the loop — always `SendMessage` the
named one so its context survives. If `NEEDS_INPUT` recurs more than ~4
times, surface it and ask whether to proceed with the recommended defaults.

**After PLAN_FINAL — post short plan comment.** Condense `plan` to a
short-form summary (goal + approach bullets + affected files; NOT every
detail) and post it to the ticket via
`add_comment(project_id=<project>, ticket_id=<#>, body=…)`.
Do not type `#ai-generated` — the MCP prepends it.

### Phase 3 — developer (Edit / Write / Bash)
Spawn `developer`. Pass the full `plan` and the `context_summary`. It
implements on the **current branch/worktree**, edits/writes files, and runs
the project's test suite (the test command is auto-detected from the stack and
named in the plan). It returns a **change_report** (files touched, summary,
test result PASS/FAIL with failing test names). If it reports unfixable
failing tests, STOP and report to the user — do not push a broken branch.

### Phase 4 — reviewer (read-only)
Spawn `reviewer`. Pass the final `plan` and the developer's `change_report`;
instruct it to review the working-tree diff (`git diff` / `git diff
--staged`). It returns `VERDICT: APPROVE` or `VERDICT: CHANGES_REQUESTED`
plus severity-tagged findings (`[blocking]` / `[nit]`).
(If the Codex plugin is active, the reviewer adds a Codex correctness pass on
its own — the verdict format and this fix loop are unchanged.)
- `CHANGES_REQUESTED` with blocking findings → re-spawn `developer` once with
  the findings appended to the plan, then re-run `reviewer` once. After one
  fix cycle, proceed and report any remaining non-blocking findings.
- `APPROVE` → proceed to the final step.

## Final step — commit, push, open draft PR, comment (orchestrator does this)

The orchestrator owns this (not the developer): it depends on the whole
pipeline's outcome (final plan + review verdict) and the branch/ticket the
orchestrator holds, and it keeps the developer's tool scope minimal.

1. **Commit** (raw git — no MCP for a local commit):
   `git add -A` then `git commit -m "<concise summary> (#<ticket>)"`.
2. **Push** the feature branch: `git push -u origin <branch>`.
3. **Open the PR as a draft via MCP** (MCP over CLI per the priority law):
   `create_pr(project_id=<project>, title=<from plan>,
   head=<branch>, base=<default branch>, draft=True,
   body=<summary + "Closes #<ticket>" + plan recap + review verdict>)`.
   Never type `#ai-generated` — the MCP prepends it.
   (`Closes #<n>` auto-links on GitHub/GitLab; if the project's provider is
   Azure DevOps or Jira this keyword differs — adjust if you ever target those.)
4. **Comment on the ticket** linking the PR:
   `add_comment(project_id=<project>, ticket_id=<#>,
   body="Draft PR opened: <PR URL>. <one-line status>")`.
5. **Report to the user:** PR URL, branch, review verdict, test result.

## Hard rules
- **Delegate everything.** Never call `get_ticket`, `Edit`/`Write`, or review
  a diff yourself. Your tools: `Agent`/`SendMessage`, `AskUserQuestion`, the
  branch-guard git reads, the final commit/push git calls, and the
  project-issues write calls (`add_comment`, `create_pr`).
- **Project id is a parameter.** Thread the supplied `project_id` into every
  subagent prompt and MCP call — never hardcode a project.
- **Subagents can't refetch.** Inline the summary/plan into each prompt.
- **Never run on main.** Enforce the branch guard up front.
- **Never create the worktree/branch.** The user owns that.
- **Push is authorized for this workflow only** (user-confirmed). PR opens as
  a **draft** so the user finalizes it.
