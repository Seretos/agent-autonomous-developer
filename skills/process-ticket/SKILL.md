---
name: process-ticket
disable-model-invocation: true
description: Takes ONE work package (a ticket id or an epic id = all its child tickets) from a prepared worktree on a feature branch all the way to a pull request with a GREEN CI pipeline — orients on the branch first (a fresh branch runs the full pipeline; a branch that already has an open, CI-green PR and a moved base runs a rebase-and-repair pass instead), planner, isolated plan critique, test-first developer, isolated test critique, reviewer (+ optional Codex pass), push (reusing an existing open PR for its head rather than opening a second), CI gate with self-repair, every step reported as a machine-readable ticket comment. The plan-critic/test-critic/review gates keep going past their nominal 3-round cap as long as each round surfaces a genuinely new finding (fingerprinted, deterministic check); once a gate only repeats findings already seen this generation, it either triggers one replan (a fresh planner dispatch with the full findings history folded in, round counters reset) or, past generation 2, fails. Never asks a human; escalates by writing a `blocked` event and ending. Invoked as "/agent-autonomous-developer:process-ticket package=<id> project_id=<project> worktree_path=<abs path> base_branch=<branch>". Never creates worktrees or branches, never touches board columns, never selects tickets — the caller owns those.
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
generation: <g>/2
rounds: plan-critic=<u>/3(<f>f,<i>i) test-critic=<u>/3(<f>f,<i>i) review=<u>/3(<f>f,<i>i) ci=<u>/3(<f>f,<i>i)
pr: <number or empty>
ci_run: <id or empty>
-->
```

`f` counts rounds that ended with real findings/failures, `i` rounds lost to
infrastructure (crash, timeout, unparseable output). **Both count toward the
cap.** The `rounds:` line carries a sixth gate, `rebase=<u>/3(<f>f,<i>i)`,
that only Phase R (see below) ever advances; a session that never enters
Phase R reports it as `0/3`. `generation` is new (see "Round caps: progress
or stagnation" below) — `1/2` on every session that never replans, `2/2` once
a replan has happened. Both fields are additive to the contract: a caller
that does not parse them loses nothing, the terminal events and their
meaning are unchanged. The event **vocabulary itself stays closed except for
this one addition** — a repair session posts nothing but the thirteen names
below, in the order Phase 0/R would produce them. Event names, exhaustively:

`started` · `plan-committed` · `plan-critic-verdict` · `tests-red` ·
`test-critic-verdict` · `tests-green` · `review-verdict` · `pr-opened` ·
`ci-red` · `replan-triggered` · `ci-green` · `blocked` · `failed`

`replan-triggered` is **not terminal** — the pipeline continues in the same
turn, at Phase 2, against a freshly re-planned `plan.md`. It exists purely so
the ticket's event history shows *why* a package that looked stuck kept
going instead of stopping, and *why* round numbers reset. See "Round caps:
progress or stagnation" and "Replan" below.

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

| gate | soft cap | hard cap | counted by |
|---|---|---|---|
| plan-critic | 3 | 6 | this skill |
| test-critic | 3 | 6 | this skill |
| review | 3 | 6 | this skill |
| CI | 3 | 3 (unchanged) | this skill |
| rebase | 3 | 3 (unchanged) | this skill (Phase R only) |

Package ceiling **per generation**: 9 gate rounds in total (plan-critic +
test-critic + review), CI excluded. A new generation (see "Replan" below)
resets this ceiling along with the per-gate counters — it is a fresh plan,
and deserves a fresh budget.

CI and rebase are unchanged from before this section existed: three rounds,
hard, no exceptions, `failed`/`blocked` on the third round's outcome — CI
findings are almost always implementation slips, not plan defects, and a
rebase either resolves mechanically or it does not (see Phase R). Neither
gate ever triggers a replan.

A session that runs **Phase R** has its own, smaller ceiling: 3 rebase rounds
+ 3 review rounds, CI excluded — Phases 1–3 do not run, so their caps do not
apply, and Phase R's own use of Phase 4 (step 5, "review only if step 1 did
not go clean") stays a plain 3-round cap too, **not** subject to the
progress/stagnation check below. A repair session earns a review of the
(small) diff a conflict resolution produced; it does not earn a replan of a
plan Phase R never even re-reads.

### Round caps: progress or stagnation

plan-critic, test-critic, and review no longer stop unconditionally at their
soft cap of 3. Instead, **on reaching the soft cap**, run
`scripts/critic/stagnation-check.py <gate> <this round's findings JSON>
<rundir>/generation-<g>-<gate>-history.json` (the script creates the history
file on first use; see its header for the exact fingerprint rule per gate).

- **`RESULT: progress`** — this round surfaced at least one finding the
  history has not seen before in this generation. Keep going exactly as
  before the cap existed: another critic/developer round, another review.
  Re-check at every subsequent round, same history file, until either the
  gate goes clean, `RESULT: stagnation` is returned, or the **hard cap of 6**
  rounds for this gate is reached in this generation (then treat it as
  stagnation regardless of what the last check said — six genuinely
  different findings on the same package is itself a sign this needs a
  human, not six more chances).
- **`RESULT: stagnation`** — every finding this round already appeared in an
  earlier round of this generation. For **plan-critic** and **test-critic**,
  and for **review**: this is where a plan-level problem is distinguished
  from an implementation slip — see "Replan" below. This is the *only* new
  branch; a gate that goes clean before ever reaching stagnation behaves
  exactly as it always did.

This directly closes ticket `#99` (`agent-chrome-wrapper` package #42, PR
#43): a review that keeps finding *new*, real problems round after round is
not a system failing to cap itself — under the old contract, staying past
round 3 needed a judgment call the reviewer was never supposed to make on
its own; under this one it is what the mechanism is built to allow, exactly
because the check is on the findings, not on a round count.

### Replan

Triggered by `stagnation` on **plan-critic**, **test-critic**, or **review**
(never CI, never rebase — see above), and only while **generation < 2**:

1. Dispatch `planner` (fresh, unnamed) with the **full** accumulated findings
   history of this generation across all three gates — not only the gate
   that stagnated — inlined verbatim, plus the current `plan.md` and
   `context_summary`. The prompt frames this explicitly as a replan: the
   existing plan has been tried and kept hitting the same objections; design
   a plan that avoids them, not a patch on the old one.
2. The result is a new `plan.md` (write it to `<rundir>`, alongside — never
   over — the previous one, which stays as `<rundir>/plan-generation-<g>.md`
   for the record).
3. **Reset all four gate counters to 0** (plan-critic, test-critic, review,
   CI — CI too, since it will run against genuinely different code) for the
   new generation. **Do not** reset the rebase counter — Phase R is
   orthogonal to generations. Start a **fresh** fingerprint history per gate
   for the new generation (a new plan earns a clean stagnation comparison;
   do not carry the old plan's findings forward as if they still applied).
4. **Increment `generation`** (1 → 2) and post the non-terminal
   `replan-triggered` event: which gate stagnated, the fingerprints that
   recurred (kind + the quoted key, not just the kind — a human reading a
   later `failed` needs to see *what* kept recurring, not just that
   something did), and the new `generation` value.
5. Continue the pipeline at **Phase 2** (plan-critic against the new plan) in
   the **same turn** — this is not a new dispatch of `process-ticket`, it is
   this session continuing. If the process dies mid-replan, the latest event
   is `replan-triggered`, which is non-terminal — the caller's existing
   "no terminal event" handling applies unchanged (see the caller's own
   `AGENTS.md`, "Waiting on CI is not a decision, and neither is a `blocked`
   event nobody tried to answer" for its side of this).

**`generation` reaching 2 and stagnating again → `failed`.** The terminal
event's text must name every fingerprint that recurred across **both**
generations, verbatim, not just its kind — the whole point of carrying the
generation history is that whoever reads the `failed` event can tell "the
plan genuinely cannot satisfy this" from "the fingerprinting mis-matched two
findings that were actually different," and only the quoted text lets them
tell the difference.

A cap hit on **CI** or **rebase** is unchanged: `failed`/`blocked` as before,
never a replan — see the table above.

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

## Phase 0 — orient on the branch

The caller hands you a worktree, not a promise about its state. A retry after
a crash, and a retry after a merge conflict, both arrive here on a branch that
already carries work. Find out which one you are in — from facts, not from a
parameter the caller might not have set. Nothing about the invocation changes;
a fresh branch on `attempt=1` runs this in a few seconds and falls straight
through to Phase 1, exactly as before this phase existed.

1. `branch = git -C <worktree_path> rev-parse --abbrev-ref HEAD`.
2. `git -C <worktree_path> fetch origin <base_branch>`.
3. `open_pr = list_prs(project_id, head=<branch>, status="open", limit=5,
   omit_body=True)`. More than one open PR for this head is not a state this
   pipeline creates → `failed`.
4. `ahead = git -C <worktree_path> log --oneline origin/<base_branch>..HEAD`
   (empty output = a fresh branch with nothing of its own yet).
5. `base_moved`: `git -C <worktree_path> merge-base --is-ancestor
   origin/<base_branch> HEAD` **fails** (the branch does not contain the
   current base).
6. `finished`: there is an `open_pr` **and** `ahead` is non-empty **and**
   `list_pipeline_runs(project_id, commit_sha=<HEAD sha>, limit=20)` returns at
   least one completed run and every completed run has
   `conclusion == "success"`. This is the discriminator between a resumed
   crash and a resumed conflict: this pipeline only opens a PR after the
   reviewer approves (Phase 4), so *an open PR plus green CI on this exact
   HEAD* means the work is done and only the base moved underneath it.
   Anything less finished means the previous attempt did not get that far.

| `finished` | `base_moved` | lane |
|---|---|---|
| yes | yes | **Phase R** — repair only. Phases 1–4 do not run. |
| yes | no | Nothing to repair: the branch already contains the current base, so whatever made the caller re-dispatch was not a conflict. Post `failed` saying exactly that, and end — one command's worth of checking here saves a whole wasted session. |
| no | yes | **Phase R steps 1–2 first** (put the existing work on the current base before continuing), then the full pipeline starting at Phase 1. |
| no | no | The full pipeline starting at Phase 1 — today's behaviour, unchanged. |

## Phase R — rebase and repair

Entered only from the table above. No new event exists for this phase — it
posts the same terminal and intermediate events Phases 1–6 always could
(`tests-green`, `review-verdict`, `pr-opened`, `ci-red`, and exactly one of
`ci-green`/`blocked`/`failed`), just fewer of them, and it advances the
`rebase=` sub-field on the `rounds:` line instead of the others.

1. `git -C <worktree_path> rebase origin/<base_branch>`.
   - Clean → the diff shape is unchanged from before the rebase; go to step 4.
   - Stopped on a conflict → step 2.
   - Any other failure → `git -C <worktree_path> rebase --abort`, post
     `failed` with the git output.
2. **Resolve — one round per stop it makes, cap 3.** Collect
   `git -C <worktree_path> diff --name-only --diff-filter=U`. Dispatch
   `developer` (fresh, unnamed, `phase=implement`) with `worktree_path`,
   `base_branch`, the conflicted file list, and the package's intent — the
   newest `<worktree_path>/.adev/*/plan.md` if one survived from an earlier
   attempt, otherwise a fresh `context-extractor` dispatch's
   `context_summary`. State the mandate narrowly in the prompt: **resolve the
   conflict markers so both sides' intent survives; do not redesign, do not
   add scope, do not touch files that are not conflicted.** When it returns,
   `git -C <worktree_path> add -A`, then `git -C <worktree_path> rebase
   --continue` — **you** do the history mutation, never the developer; it
   only stages resolved files. A further stop is the next round.
3. Three rounds without a finished rebase, or the developer reporting the two
   sides as a genuine, incompatible design decision rather than a mechanical
   conflict → `git -C <worktree_path> rebase --abort`, then post `blocked`
   (the question, 2–4 options, a recommendation, what you checked) or
   `failed`, whichever fits what happened.
4. **Re-verify.** Dispatch `developer` (fresh, `phase=implement`): "the change
   is already made; run the full suite and fix only what the rebase broke."
   Post `tests-green` ("local pre-filter only — CI decides").
5. **Review only if step 1 did not go clean.** A conflict changed the diff, so
   it earns Phase 4 unchanged (its own 3-round cap). After a clean rebase
   nothing but the base moved — skip the reviewer entirely.
6. Continue at **Phase 5** (push + PR) and then **Phase 6** (CI gate), both
   unchanged.

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
major). A critical still open at the soft cap (round 3) → run the
progress-or-stagnation check ("Round caps: progress or stagnation", above)
before deciding anything: `progress` keeps this loop going past round 3;
`stagnation` triggers a replan (or `failed`, at `generation` 2).

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
  (it rewrites only the assertions named), critique again. At the soft cap
  (round 3) with a `critical` still open, run the progress-or-stagnation
  check as in Phase 2 — `progress` continues, `stagnation` replans (or
  `failed` at `generation` 2).
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
  re-review — never narrowed to "were the findings fixed". At the soft cap
  (round 3) with blocking findings still open, run the progress-or-stagnation
  check against the reviewer's structured findings block (`agents/reviewer.md`,
  "What you return") — `progress` continues past round 3 (this is exactly
  ticket `#99`'s case), `stagnation` replans (or `failed` at `generation` 2).
- `APPROVE` → Phase 5.

## Phase 5 — commit, push, PR

1. `.gitignore` guarantee already done in preconditions; verify `.adev/` is
   ignored (`git -C <worktree_path> check-ignore .adev`).
2. `git -C <worktree_path> add -A`, then commit. Single-line: `-m "<summary>
   (#<ticket>)"`. Multi-line: Write the message to `<rundir>/commit-msg.txt`,
   `git -C <worktree_path> commit -F <rundir>/commit-msg.txt`. Never a
   PowerShell here-string through the Bash tool.
3. `git -C <worktree_path> push -u origin <branch>`. If it is rejected as
   non-fast-forward *and* you rewrote this branch's history in this session
   (Phase R ran a rebase), retry **once** with `--force-with-lease`. **Never
   bare `--force`.** A `--force-with-lease` rejection means somebody else
   pushed to this branch while you worked — post `failed` saying so; do not
   overwrite them.
4. **Open or reuse the PR.** Use `open_pr` from Phase 0 if you have it fresh;
   otherwise re-read `list_prs(project_id, head=<branch>, status="open",
   limit=5, omit_body=True)`.
   - **No open PR** → `create_pr(project_id, title=<from plan>, head=<branch>,
     base=<base_branch>, draft=False, body=<summary + plan recap + review
     verdict + one "Closes #<n>" line per ticket in the package>)`. Not a
     draft: the caller merges on `ci-green`; a human never has to finalize it.
   - **Exactly one open PR** → it is yours (this branch is named for this
     package and nothing else pushes to it): **reuse it**, never open a
     second. `update_pr(project_id, pr_id=<n>, title=…, body=…)` with the
     same content `create_pr` would have received, plus one extra line when
     Phase R rebased: `Rebased onto <base_branch> at <sha>.`
   - **More than one open PR** → this cannot happen (Phase 0 already checked
     and would have failed); if you reach this branch anyway, post `failed`.
5. Post `pr-opened` with `pr:` filled — the reused number when you reused one.

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
  and `sleep` calls named above and for invoking
  `scripts/critic/stagnation-check.py` (deterministic, no model — see "Round
  caps: progress or stagnation"), and these MCP calls: `list_projects`,
  `add_comment`, `create_pr`, `list_prs`, `update_pr`, `list_pipeline_runs`,
  `get_pipeline_run`, `get_pipeline_step_log`. Nothing else — in particular no
  `get_pr` and no `merge_pr`: mergeability and merging are the caller's
  concern, not this skill's.
- **No human in the loop.** `AskUserQuestion` does not exist for you. A
  question is a `blocked` event. A retry is never a question.
- **Every return trip is a fresh dispatch with everything inlined.** Subagents
  cannot refetch; re-inline plan, findings, change report each time.
- **Never on main, never create the branch/worktree, never `-C`-less git.**
- **Never move a board column.** The caller owns the board.
- **One terminal event, then stop.** Do not keep working after `ci-green`,
  `blocked`, or `failed`. `replan-triggered` is the one non-terminal event
  that is *expected* to be followed by more work in the same turn — see
  "Replan".
- **Commit and push before every turn end, and never end a turn to wait.**
  See *Turn-end discipline*; a `Stop` hook enforces both.
- **No "not included" lists.** A package is done when all of it is done. If
  part of it cannot be done, that is `blocked` or `failed`, not a PR with a
  caveat.
