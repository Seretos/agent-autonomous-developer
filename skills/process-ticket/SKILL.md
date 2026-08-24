---
name: process-ticket
disable-model-invocation: true
description: Takes ONE work package (a ticket id or an epic id = all its child tickets) from a prepared worktree on a feature branch all the way to a pull request with a GREEN CI pipeline — planner, isolated plan critique, test-first developer, isolated test critique, reviewer (+ optional Codex pass), push, PR, CI gate with self-repair, every step reported as a machine-readable ticket comment. Never asks a human; escalates by writing a `blocked` event and ending. Invoked as "/agent-autonomous-developer:process-ticket package=<id> project_id=<project> worktree_path=<abs path> base_branch=<branch>". Never creates worktrees or branches, never touches board columns, never selects tickets — the caller owns those.
---

# process-ticket — one work package → one green PR

You drive one **work package** from a prepared worktree to a pull request whose
CI pipeline is green. You do it exclusively through subagents and the bundled
critic runners. You do not read code, write the plan, edit files, or review a
diff yourself — you sequence, thread context, count rounds, post events, and do
the git/PR/CI steps at the end.

There is nobody to ask. This skill runs in a headless session with
`AskUserQuestion` disallowed. Every question that cannot be answered from the
ticket, its comments, its siblings and the code is a **`blocked` event** that
ends the run — the caller and, last, a human decide. A question is never a
reason to wait.

## Parameters

| parameter | required | meaning |
|---|---|---|
| `package` | yes | a ticket id, or an epic id. An epic means **all** its child tickets (`list_hierarchy`): one branch, one PR, one `Closes #<n>` per child |
| `project_id` | yes | the project-issues project. Never guessed — if missing, STOP with a `failed` event |
| `worktree_path` | yes | absolute path of the prepared worktree. Every git call is `git -C <worktree_path> …`; never rely on cwd |
| `base_branch` | yes | the PR base (usually the default branch) |
| `attempt` | no | caller's attempt counter, default 1; copied into every event |

## Events — the contract with whoever called you

State lives in the ticket, not in your return value. After every phase you post
a comment on the **package ticket** (the epic, if the package is an epic) via
`add_comment` (the MCP prepends `#ai-generated`; never type it). Each comment
starts with a machine block, then one short human-readable paragraph:

```
<!-- adev:event v1
event: <name>
package: <id>
attempt: <n>
rounds: plan-critic=<u>/3(<f>f,<i>i) test-critic=<u>/3(<f>f,<i>i) review=<u>/3(<f>f,<i>i) ci=<u>/3(<f>f,<i>i)
pr: <number or empty>
ci_run: <id or empty>
-->
```

`f` counts rounds that ended with real findings/failures, `i` rounds lost to
infrastructure (crash, timeout, unparseable output). **Both count toward the
cap.** Event names, exhaustively:

`started` · `plan-committed` · `plan-critic-verdict` · `tests-red` ·
`test-critic-verdict` · `tests-green` · `review-verdict` · `pr-opened` ·
`ci-red` · `ci-green` · `blocked` · `failed`

Terminal events: **`ci-green`** (the only success), **`blocked`** (needs a human
*decision*: the text carries the question, 2–4 options, a recommendation, and
what you already checked), **`failed`** (a cap was exhausted or infrastructure
broke — the text says which rounds were findings and which were infrastructure,
so the reader can decide instead of just retrying). Secure the work first (see
*Turn-end discipline*), then post exactly one terminal event, then end your
turn.

## Turn-end discipline

You run headless (`claude -p`). There is no loop that wakes you after your turn
ends, so **ending your turn ends this process**. Two rules follow, and a
mechanical `Stop` hook enforces both — if it blocks you, do what it says rather
than trying to end the turn again.

1. **Never end your turn waiting for something.** Anything long — the CI poll,
   a suite run you started yourself — runs *inside* the turn: a blocking
   `Bash("sleep 60")`, or `Bash(run_in_background: true)` followed by an in-turn
   `Monitor` wait. Backgrounding a command and ending the turn "to be resumed
   when it finishes" does not suspend you, it kills you and the command with
   you. This is not tunable: `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` only sets
   how long the process loiters before it is killed — measured at 600 s, at `0`
   and at 2 h, all three died the same way (ticket #23).
2. **Never end your turn with work no remote has.** Before *every* ending —
   `ci-green`, `blocked`, `failed`, and any point at which you are about to
   stop for any other reason — `git -C <worktree_path> add -A`, commit, and
   `git -C <worktree_path> push -u origin <branch>`. The caller removes this
   worktree after a failed second attempt, so uncommitted work is destroyed and
   the retry re-pays for context, planning and critique; a retry that finds
   committed work continues from it instead. Commit even work you do not rate:
   a discarded commit costs nothing, a lost implementation costs the whole
   attempt. If the push itself fails, say so in the terminal event's text.

## Round caps

| gate | cap | counted by |
|---|---|---|
| plan-critic | 3 | this skill |
| test-critic | 3 | this skill |
| review | 3 | this skill |
| CI | 3 | this skill |

Package ceiling: 9 gate rounds in total, CI excluded. An infrastructure-failed
round counts. When a cap is hit with a `critical` finding, a `CHANGES_REQUESTED`
verdict, or a red pipeline still open → `failed`, never "proceed anyway".

## Preconditions

1. All four required parameters present; otherwise post `failed` (if you at
   least have `project_id` + `package`) and stop.
2. **Worktree guard.** `git -C <worktree_path> rev-parse --abbrev-ref HEAD` is
   not `main`/`master`; `git -C <worktree_path> rev-parse --git-dir` ≠
   `--git-common-dir` (otherwise this is a main checkout, not a worktree).
   Violation → `failed`.
3. **MCP presence.** `list_board_columns` is not needed here. Call
   `list_projects(fields="light")`; if the project-issues tools are missing, you
   cannot even post an event — end with a plain-text failure naming
   `/reload-plugins`.
4. Create `<rundir>` = `<worktree_path>/.adev/<package>-<attempt>/` and ensure
   `.adev/` is in the target repo's `.gitignore` (idempotent one-line append,
   done **before** the first commit so the append lands in this package's own
   commit).
5. Post `started`.

## Phase 1 — context-extractor (read-only)

Dispatch `context-extractor` with `project_id`, `package`. It returns two
things: a distilled **`context_summary`** and a **verbatim transcript** of the
package (title, body, every comment, and — for an epic — every child ticket's
title, body and comments). Write the transcript to `<rundir>/spec.md` with the
Write tool, byte-for-byte. The spec is what the plan critics judge against;
nothing may paraphrase it on the way.

If the extractor reports the MCP unavailable, end as in precondition 3.

## Phase 2 — planner → plan-critic (question-free)

Dispatch `planner` synchronously and unnamed with `context_summary` and
`worktree_path`. It ends with `STATUS: PLAN_FINAL` or `STATUS: NEEDS_INPUT`.

- `PLAN_FINAL` → write the plan to `<rundir>/plan.md`; post `plan-committed`
  with the short-form plan (goal, approach bullets, affected files).
- `NEEDS_INPUT` → **you try to answer first.** Read the transcript you already
  hold (`spec.md`): the epic body, sibling tickets, prior comments, the code
  references the planner cites. If the answer is there, re-dispatch the planner
  (fresh, unnamed) with the previous plan draft verbatim plus your answer keyed
  to the question number and the instruction to fold it in, not start over. Cap
  two such rounds. If the question is a genuine decision the context does not
  settle → post `blocked` (question, options, recommendation, what you checked
  and why it was not enough) and end.

**Plan critique.** Dispatch `plan-critic` (fresh, unnamed) with `spec_file`,
`plan_file`, a one-paragraph scope statement (what this package covers, round
number), `output_dir=<rundir>/plan-critic-<round>/`. It runs three isolated
`claude -p` critics and a mechanical merge and returns `GATE_RESULT: OK` with
severity counts and findings, or `GATE_RESULT: INFRA_FAILURE`.

- `INFRA_FAILURE` → the round counts as `i`; re-dispatch. Three infra rounds →
  `failed`.
- Any `critical` → the round counts as `f`; re-dispatch the **planner** (fresh)
  with the plan verbatim plus the critical findings, then critique again.
- `major` → your call: route it to the planner if it concerns the package's
  scope, else note it in the plan comment as accepted with one line of reason.
- `minor` → proceed.
- Findings of kind `unverified-assumption` and the `unverifiable_…` list are
  **not** defects. The critics have no repository access; the planner grounded
  the plan in code and you do not second-guess that with a critic that could not
  see it.

Post `plan-critic-verdict` after every round (counts + one line per critical/
major). A critical still open after round 3 → `failed`.

## Phase 3 — developer, test-first, with the test critique between RED and GREEN

Two developer dispatches, both fresh and unnamed.

**3a — tests (`phase=tests`).** Dispatch `developer` with `plan`,
`context_summary`, `worktree_path`, `phase=tests`. It writes the driving tests
for every behavioural requirement, confirms each fails for the expected reason
(valid RED), and returns the RED evidence plus the list of test files. Post
`tests-red`. Then write the verbatim test diff to `<rundir>/tests.diff`
(`git -C <worktree_path> diff -- <test files>` plus `git diff --no-index
/dev/null <new file>` for untracked ones) and dispatch `test-critic` (fresh,
unnamed) with `plan_file`, `tests_file=<rundir>/tests.diff`,
`output_dir=<rundir>/test-critic-<round>/`.

- `INFRA_FAILURE` → `i`, re-dispatch; three → `failed`.
- `critical` → `f`; re-dispatch the developer `phase=tests` with the findings
  (it rewrites only the assertions named), critique again. Three → `failed`.
- `major`/`minor` → forward to 3b as notes; proceed.

Post `test-critic-verdict` per round. Non-behavioural packages (docs, config,
pure refactor) have no driving test: the developer says so in 3a, 3b keeps the
suite green, and the test critique is skipped with one line in `tests-red`'s
text saying why.

**3b — implementation (`phase=implement`).** Dispatch `developer` with `plan`,
`context_summary`, `worktree_path`, `phase=implement`, the test-critic notes.
It implements to GREEN and runs the **full suite** locally, backgrounded with an
in-turn `Monitor` wait. It returns the change report with GREEN evidence and the
full-suite result.

- `PASS` → post `tests-green` (text: "local pre-filter only — CI decides").
- `FAIL` with a named blocker the developer could not resolve → one fresh
  re-dispatch with the failure tail; still `FAIL` → `failed` (infra or findings,
  say which).
- A report without PASS/FAIL **and** without an explicit `blocked/in-progress`
  status is incomplete: one fresh re-dispatch noting that the previous attempt
  returned without running the suite; twice → `failed`.
- `blocked/in-progress` → the developer handed you a wait it could not finish
  inside its turn. Re-dispatch fresh with the log path; never `SendMessage`.

## Phase 4 — reviewer

Dispatch `reviewer` (fresh, unnamed) with `plan`, `change_report`,
`worktree_path`, `base_branch`. It returns `VERDICT: APPROVE` or
`VERDICT: CHANGES_REQUESTED` with `[blocking]`/`[nit]` findings (Codex pass
folded in when available). Post `review-verdict`.

- `CHANGES_REQUESTED` → `f`; fresh developer dispatch (`phase=implement`, plan +
  findings appended, prior change report inlined), then a fresh **full**
  re-review — never narrowed to "were the findings fixed". Three rounds with
  blocking findings still open → `failed`.
- `APPROVE` → Phase 5.

## Phase 5 — commit, push, PR

1. `.gitignore` guarantee already done in preconditions; verify `.adev/` is
   ignored (`git -C <worktree_path> check-ignore .adev`).
2. `git -C <worktree_path> add -A`, then commit. Single-line: `-m "<summary>
   (#<ticket>)"`. Multi-line: Write the message to `<rundir>/commit-msg.txt`,
   `git -C <worktree_path> commit -F <rundir>/commit-msg.txt`. Never a
   PowerShell here-string through the Bash tool.
3. `git -C <worktree_path> push -u origin <branch>`.
4. `create_pr(project_id, title=<from plan>, head=<branch>, base=<base_branch>,
   draft=False, body=<summary + plan recap + review verdict + one
   "Closes #<n>" line per ticket in the package>)`. Not a draft: the caller
   merges on `ci-green`; a human never has to finalize it.
5. Post `pr-opened` with `pr:` filled.

## Phase 6 — CI gate (the only verdict)

A local PASS was a pre-filter. The pipeline decides.

1. `head = git -C <worktree_path> rev-parse HEAD`.
2. Poll **in this turn**: `list_pipeline_runs(project_id, commit_sha=head,
   limit=20)`; if no run exists yet or any run has `status != "completed"`,
   `Bash("sleep 60")` — blocking, in the foreground — and poll again. Cap 45
   minutes per round; a cap hit is an `i` round. Never poll from inside a
   subagent (its background processes die with its turn), and never poll by
   backgrounding something and ending your own turn either — see *Turn-end
   discipline*: ending your turn ends this process.
3. All runs `conclusion == "success"` → post **`ci-green`** with `ci_run:` and
   end. Done.
4. Any failure → post `ci-red` (`f`), then for the failing run:
   `get_pipeline_run(project_id, run_id, include_failure_excerpt=True)` and
   `get_pipeline_step_log(project_id, run_id, job_id, mode="around_failure")`.
   Classify:
   - a **finding** (test failure, lint, build error caused by the diff) → fresh
     developer dispatch (`phase=implement`, plan + the failing job excerpt), then
     a fresh full review (Phase 4, its own counter), then commit/push/poll again;
   - **infrastructure** (runner lost, timeout unrelated to the diff, workflow
     misconfiguration not introduced by this package) → `i`; re-run by pushing
     an empty commit (`git -C <worktree_path> commit --allow-empty -m "ci:
     retry (#<ticket>)"`) and poll again.
5. Three CI rounds without green → `failed`. The text must separate `f` from
   `i` rounds and quote the last failing job.

## Hard rules

- **Delegate everything.** Your own tools: `Agent` (always unnamed, always
  `run_in_background: false`, always a fresh call — never `name`, never
  `SendMessage`), `Read`/`Write` for `<rundir>` files only, `Bash` for the git
  and `sleep` calls named above, and these MCP calls: `list_projects`,
  `add_comment`, `create_pr`, `list_pipeline_runs`, `get_pipeline_run`,
  `get_pipeline_step_log`. Nothing else.
- **No human in the loop.** `AskUserQuestion` does not exist for you. A
  question is a `blocked` event. A retry is never a question.
- **Every return trip is a fresh dispatch with everything inlined.** Subagents
  cannot refetch; re-inline plan, findings, change report each time.
- **Never on main, never create the branch/worktree, never `-C`-less git.**
- **Never move a board column.** The caller owns the board.
- **One terminal event, then stop.** Do not keep working after `ci-green`,
  `blocked`, or `failed`.
- **Commit and push before every turn end, and never end a turn to wait.**
  See *Turn-end discipline*; a `Stop` hook enforces both.
- **No "not included" lists.** A package is done when all of it is done. If
  part of it cannot be done, that is `blocked` or `failed`, not a PR with a
  caveat.
