# agent-autonomous-developer

Pure skill + agents plugin (no binary, no MCP). Takes **one work package** — a ticket, or an epic standing for all its child tickets — from a prepared worktree to a pull request with a **green CI pipeline**, for projects in any language (stack auto-detected), on top of the `agent-project-issues` MCP.

README.md covers *what* it does, install, and release. The skill and the agents document their own rules. This file records only the non-obvious decisions a contributor must not silently break — the cross-file invariants and the rationale you cannot reconstruct from any single file.

## Tool priority

Skills and MCP tools take priority over raw file tools — and this **explicitly overrides** the generic harness default that says "prefer the dedicated file/search tools (Glob/Grep/Read)". When a skill or MCP tool covers the task, reach for it first; fall back to raw Glob/Grep/Read only when none applies.

## Scope: one package in, one green PR out — nothing above that

This plugin has exactly one skill, `process-ticket`, and it is not model-invocable: the caller is a headless `claude -p` session started by an orchestrator (in the Seretos ecosystem, `agent-ticket-orchestrator`), or a human typing the slash command in a worktree. The plugin knows **nothing** about boards, ticket selection, bundling, worktree lifecycle, or other packages. It used to carry a fleet layer (`orchestrate-tickets`, wave scheduling, a `dispatch` lane router, a `conflict-analyst`); all of that moved up and out in the 2026-08 rebuild, for a reason that is still load-bearing: parallelism inside one repository bought nothing and cost the entire B6 liveness apparatus, while a lower plugin that knows about the board cannot be reused by a caller with a different board. Do not add ticket selection, column writes, or multi-package logic here.

## The contract with the caller is a write obligation, not a return schema

A headless dispatch returns "process ended" plus text. That channel is structurally too poor to carry state, and a caller that reconstructs state from prose is a bug waiting to happen. So `process-ticket` owes the caller a **fixed set of comment events** on the package ticket (`<!-- adev:event v1 … -->`, names and fields in `skills/process-ticket/SKILL.md` → "Events"). The caller derives everything from the latest event. Three invariants follow:

- The event vocabulary is **closed**. Adding an event is a contract change; tell the caller's maintainers (`agent-ticket-orchestrator/AGENTS.md` carries the same table). `replan-triggered` (2026-08-25) is the one addition since the vocabulary was fixed — additive and non-terminal, see "Round caps are progress-based, not just round-counted" below.
- Exactly **one terminal event** per run (`ci-green`, `blocked`, `failed`), posted last, then the turn ends. A run that keeps working after a terminal event makes the caller act on a stale state. `replan-triggered` is the deliberate exception: it is non-terminal by design, and more work in the same turn is expected to follow it.
- The `rounds:` line must distinguish findings rounds (`f`) from infrastructure rounds (`i`). A human who reads a `failed` event has to be able to tell "three real critiques" from "three crashes" — they are different problems with different fixes. It also now carries `generation:` alongside it (see below).

## Phase 0 orients on the branch instead of taking a parameter

A retry can arrive on a branch in two different states — one where the previous
attempt crashed mid-pipeline, and one where the previous attempt finished, got
reviewed, opened a PR and went CI-green, but the merge failed because the base
moved underneath it. Those two need opposite treatment: the first needs the
whole pipeline again, the second needs only a rebase. `process-ticket` tells
them apart itself, from facts, in `skills/process-ticket/SKILL.md`'s Phase 0 —
**deliberately not from a parameter the caller sets.** The caller (this
ecosystem's `agent-ticket-orchestrator`) cannot reliably distinguish "crashed"
from "finished but conflicted" without duplicating this skill's own state
machine; the discriminator this skill actually has is cheap and exact: *an
open PR for this branch's head, with every CI run on the exact current HEAD
green,* since this pipeline never opens a PR before Phase 4 (review) approves.
Anything less finished than that is a resumed crash, not a resumed conflict,
and gets the full pipeline. This also means `agent-ticket-orchestrator`'s
retry dispatch is byte-identical whether it is retrying a crash or retrying a
conflict — see its `AGENTS.md`, "Merge outcomes are classified, and a conflict
is a retry".

No new event exists for the repair path (Phase R). The vocabulary stays
**closed** — Phase R posts the same events Phases 1–6 could always post, just
fewer of them, and advances a new `rebase=` sub-field on the existing
`rounds:` line rather than inventing a sixth gate name. A caller that ignores
the sub-field loses nothing; it is opaque prose exactly like the rest of
`rounds:`.

**One branch has at most one open PR, ever.** Phase 0 looks up any existing
open PR for its head before doing anything else, and Phase 5 reuses it
(`update_pr`) instead of calling `create_pr` a second time. This was a latent
bug independent of the conflict-retry feature: before this change, a second
attempt on the same branch called `create_pr` unconditionally and would have
either duplicated the PR or errored, silently, the first time any retry
reached Phase 5 with a PR already open.

## There is no human in this process, by construction

The dispatching CLI passes `--disallowedTools AskUserQuestion`, and no agent definition here grants it. A question is a **`blocked` event** and the end of the run. Before posting one, `process-ticket` must have tried to answer from the package transcript (epic body, sibling tickets, prior comments, the code the planner cites) and must say in the event what it checked and why that was not enough — escalating is not forwarding. The human is asked for a **decision**, never for a **retry**: anything whose answer would be "try again" is covered by the round caps. A `blocked` event whose only sensible reaction is "kick it again" is a bug in this plugin.

## Every Agent dispatch is unnamed, synchronous, fresh

A named `Agent(...)` spawn delivers on a `SendMessage` mailbox nothing here listens to; the caller waits for a task-notification that never comes (`#60`, `#88`). Resuming an existing agent via `SendMessage` is the same channel by another name. Every round trip — planner answer rounds, critic rounds, developer fix rounds, re-reviews, CI repairs — is a **fresh unnamed `Agent(..., run_in_background: false)` call with everything re-inlined** (plan, findings, prior change report). Subagents cannot refetch. The same rule is ecosystem-wide (root `AGENTS.md`); this plugin is where it was learned.

The same non-suspension applies one level down, inside a single developer dispatch: a subagent that ends its turn while it backgrounded a shell command does not get suspended and later resumed either — the harness kills the background process and the turn's "I'll resume once it completes" is never honored (ticket `#93`, a live recurrence of the exact failure mode `#83`/`#88` already fixed at the fleet layer, this time inside a single dispatch). `agents/developer.md`'s prose Hard Rule forbidding this was already in place when `#93` happened — a live incident proved prose alone is not reliable enough — so it got a mechanical backstop: the `SubagentStop` hook `hooks/check-developer-background-wait.mjs` (wired in `hooks/hooks.json`, matcher `developer`) scans the developer's own transcript for a backgrounded `Bash` call and blocks the stop.

## Nothing runs in the background — not even with a `Monitor` (ticket #101)

Until 2026-08-26 the rule above had a sanctioned escape: background the full suite (`nohup … &`) and wait for it **in-turn** with the `Monitor` tool, which the two turn-end hooks accepted as "resolved". `agents/developer.md` even *mandated* that shape for every full-suite run, on the theory that the foreground `Bash` timeout (10 min) is shorter than real suites. `agent-worktree#176` killed that theory twice in one day: attempt 1 backgrounded the suite, armed a `Monitor`, wrote *"Nothing more to do until that fires"* and ended its turn — the hooks saw the `Monitor` and let the stop through, and nothing ever fired, because nothing wakes a headless process; attempt 2 backgrounded a suite with a hanging test and was killed by the harness's 600 s ceiling with the hang's diagnostics inside it. Both sessions had a project `AGENTS.md` in front of them that said *never background the suite* in so many words; the plugin's own instruction said the opposite, louder, and won. Between `#93` (2026-08-23, "backgrounding the verification run is a bug") and `#176` the mandatory-background paragraph had crept back into `developer.md` through a later ticket — which is why this rule now has a doc regression test (`tests/test_no_background_rule.py`), not just prose.

The rule is now absolute and lives in three places that must agree: `agents/developer.md` (step 4 + Hard Rules), `agents/reviewer.md` (Hard Rules), `skills/process-ticket/SKILL.md` ("Turn-end discipline"). **No test run, build or wait is ever started with `run_in_background: true`, `nohup … &`, `Start-Job`, `Start-Process` or `Monitor`.** A suite that does not fit one call runs as synchronous chunks, one foreground `Bash` call each with an explicit `timeout` (max 600 000 ms), the project `AGENTS.md`'s chunks if it names any. A chunk that hits its timeout is *information* — re-run it with a per-test timeout that dumps stacks (`pytest --timeout=<n> --timeout-method=thread` or the project's equivalent) and carry the dump into the change report and the `failed` event; those stacks are exactly what `#176` never produced. There is no legitimate exception; a case that seems to need one is a `blocked` event.

Mechanically, three hooks in `hooks/hooks.json` enforce it, all sharing one classifier (`backgroundReasonForBash` in `hooks/lib/turn-end-scan.mjs` — `run_in_background: true`, `nohup`, `Start-Job`, `Start-Process`, trailing `&`): the `PreToolUse` hook `hooks/check-no-background.mjs` (matcher `Bash|Monitor`) refuses the call before it runs, exit 2 with the reason on stderr; the `SubagentStop` (`#93`) and `Stop` (`#23`) hooks are the backstop behind it and block a turn ending with a backgrounded command outstanding. Since `#101` a `Monitor` call resolves **nothing** in that walk — the only thing that does is the PreToolUse refusal itself, recognised by the `[adev-no-background]` marker it leaves in the transcript, so a refused call cannot trap the agent behind a stop it has no way to satisfy. **Keep the classifier, the prose rule, the doc test and the hook scope gate in sync**: the PreToolUse hook fires in every session that loads this plugin, so it is scoped like the `Stop` hook (presence of `<cwd>/.adev/`) **or** to one of this plugin's own `agent_type`s; a human's interactive session keeps `Monitor`. To exercise it by hand: `mkdir .adev` in any directory and run `claude -p` there with a prompt that tries a backgrounded command.

And it applies one level *up* as well, to the top-level session: headless (`claude -p`) there is no loop that wakes the session after its turn ends, so **the session ending its turn ends the process** (ticket `#23`). This was measured, not assumed — `lib-python-worktree` #140 was run three times with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` unset (default 600 s), at `0`, and at `7200000`, and died the same way each time; `0` in particular means *no* wait, not "wait indefinitely" as the harness's own hint line claims. The env var sets how long the process loiters before it is killed; it never turns waiting into resuming, so **do not "fix" #23 by setting it**. The backstop is the `Stop` hook `hooks/check-session-turn-end.mjs`, wired in `hooks/hooks.json` without a matcher, which blocks the stop on two conditions: an outstanding backgrounded `Bash` call (same detection as the `#93` hook — the walk is shared in `hooks/lib/turn-end-scan.mjs`, change it in one place and both levels move together; since `#101` a `Monitor` no longer counts as resolving it), and a worktree holding changes or commits that no remote has. The second condition is the one that pays: the caller prescribes `worktree_remove` after a failed second attempt, so unpushed work is destroyed and the retry re-pays for context, planning and critique (`#22`; on #140 it was 1979 insertions across 15 files, on #139 the same loss had already happened and was recovered by hand as a patch). It is scoped by the presence of `<cwd>/.adev/` — a `Stop` hook otherwise fires in every session that loads this plugin, including a human's — and capped at one block per turn via `stop_hook_active`. **Keep the scope gate and precondition 4 in sync**: if `process-ticket` stops creating `<worktree_path>/.adev/<package>-<attempt>/`, or the caller stops starting the session with cwd = the worktree, the hook silently stops firing.

## CI is the verdict; the local suite is a pre-filter

The developer still runs the full suite locally (synchronous foreground chunks inside its turn, never backgrounded — see `agents/developer.md` step 4 and "Nothing runs in the background" above) because it is cheaper to fix locally than on the runner. But the event for it says `tests-green` with "local pre-filter only", and the only success event is `ci-green`. Two reasons: local runs crash regularly on this platform, and a CI result was produced by nobody with a stake in the outcome — the same argument as critic isolation, applied to tests.

Polling the pipeline (`list_pipeline_runs(commit_sha=HEAD)` + `Bash("sleep 60")`) happens in **`process-ticket`'s own turn**, never inside a subagent: a subagent's background processes die with its turn and its task-notifications go to the parent, which is exactly the silent stall `#88` documented. It also happens *inside* that turn — the `sleep` is a blocking foreground call, not a backgrounded one the session then ends its turn to wait for; that variant kills the process (`#23`, above). The 45-minute cap per CI round counts as an infrastructure round when hit.

## Critic isolation is a property of the process, not of the prompt

`plan-critic` and `test-critic` (`agents/`) are ordinary subagents, but the critique itself runs in separate `claude -p` processes started by `scripts/critic/*-run.sh` with `--setting-sources "" --strict-mcp-config --disable-slash-commands --tools "" --system-prompt <file> --json-schema <file>`, cwd a `mktemp -d` **outside** the repository (CLAUDE.md discovery walks parent directories; a subdirectory of the repo would defeat the isolation). The review package is assembled by a script from verbatim inputs — the ticket transcript, the plan, the test diff — because the curator of a package is the one role that could defang a critique. The merge (`plan-critic-merge.py`) is deterministic code with no model in it: a model between the critics and the decision would be a curator again. `check-critic-isolation.sh` runs as a static pre-flight on every gate invocation; run it with `--live` after every CLI upgrade.

A critic has no repository access. Its claims about existing code are `unverified-assumption` findings, and **`process-ticket` never upgrades them to defects** — the planner, which could see the code, is trusted over a critic that could not.

Ported from the `sothis` project's gates (2026-08); the flag set is identical across both runners on purpose, and `check-critic-isolation.sh` refuses to run if one runner drops a flag the other keeps.

## Round caps are progress-based, not just round-counted (2026-08-25)

plan-critic, test-critic, and review each have a **soft** cap of three rounds and a **hard** cap of six; CI and rebase keep their original hard cap of three, unchanged. `process-ticket` counts; a critic never counts its own rounds. An infrastructure-failed round still counts toward the soft cap — exempting it would turn the cap into an unbounded retry loop.

The reason for the split: a fixed round count cannot tell "the same objection dwelling at round 3" from "three genuinely different objections, one per round" — and only the first of those is actually a decision-shaped problem. `agent-ticket-orchestrator#7`/`#8` diagnosed the same confusion one layer up (a retry burned on a case a retry cannot fix); `agent-plugin-dev#21` Problem 2 worked out the fix for this layer, and a live incident (`#99`, `agent-chrome-wrapper` package #42/PR #43 needing 5 review rounds, each with a genuinely new finding) confirmed the diagnosis before this was built.

At the soft cap, `scripts/critic/stagnation-check.py` (deterministic, no model — same philosophy as `plan-critic-merge.py`) compares this round's findings against a per-generation fingerprint history: `(kind, violated_criterion)` for plan-critic/test-critic, `(kind, file, what[:80])` for review (the reviewer has no requirement IDs to quote, see `agents/reviewer.md`'s additive structured findings block). A genuinely new fingerprint is progress — keep going, up to the hard cap of six. Only fingerprints already seen this generation is stagnation — and stagnation on plan-critic/test-critic/review (never CI, never rebase) triggers **one replan**: a fresh `planner` dispatch with the full findings history inlined, all four gate counters reset, `generation` incremented (capped at 2). Stagnating again at generation 2 is `failed`, with every recurring fingerprint quoted verbatim in the text — full mechanism in `skills/process-ticket/SKILL.md`, "Round caps: progress or stagnation" and "Replan".

The reviewer formerly had one fix cycle and no defined path for "still blocking after it"; that gap is closed by the same progress/stagnation logic, not by a bare cap-and-`failed` any more.

## Test-first is two developer dispatches with a gate between them

`phase=tests` writes the driving tests and proves RED; `test-critic` judges whether a wrong implementation would still pass them; `phase=implement` makes them GREEN. The split exists so the critique happens *before* production code biases what the tests are allowed to check. Non-behavioural packages skip the gate explicitly (the developer says so in `tests-red`'s text) — there is no manufactured RED for a docs change.

## Developer and reviewer tool boundaries are denylists

`developer` and `reviewer` use `disallowedTools:` (not `tools:`) so they inherit whatever MCP tools a session connects (Serena, Unity, future servers) while still being blocked from the operations they must never do: the PR/merge/ticket-write MCPs, worktree create/remove, and — for the reviewer — every editing tool. `planner`, `context-extractor`, `plan-critic`, `test-critic` keep an allowlist; they have narrow, known needs. Keep the asymmetry.

## Stack detection lives in the planner and the developer, nowhere else

The planner detects the stack from config files (`pyproject.toml` → `python -m pytest`, `package.json` → `npm test`, `go.mod`, `Cargo.toml`, …) and pins the concrete commands in the plan; the developer runs those (re-deriving if the plan is thin). The skill and the critic scripts are stack-neutral. Project-specific build/test knowledge belongs in a skill of the *target* project, never in this plugin.

## Every git call carries `-C <worktree_path>`

The invoking session's cwd is not pinned to the worktree (`#66`). `process-ticket`, `developer`, and `reviewer` all receive `worktree_path` and never issue a bare `git` command. Multi-line commit messages go through `git commit -F <file>`, never a PowerShell here-string via the Bash tool (which runs real bash and would commit a subject of `@`).

## Release payload must ship every `${CLAUDE_PLUGIN_ROOT}`-referenced file (ticket #81)

`release.yml` stages `skills/`, `agents/`, `scripts/` (recursively, so `scripts/critic/` rides along), `hooks/`, `assets/`, `description.md`; `tools/check_plugin_payload.py` scans `skills/**/*.md` and `agents/*.md` for `${CLAUDE_PLUGIN_ROOT}/...` references and fails the build if a referenced file is not staged. The critic runners, schemas, prompts and constraints are referenced from `agents/plan-critic.md` / `agents/test-critic.md` — keep them under `scripts/`.

## The marketplace dispatch payload carries a `changelog` field (ticket #97)

The same notes body `--generate-notes` already produced for the GitHub Release, one step earlier — read back via `gh release view <tag> --json body`, never recomputed a second time so the two can't drift. `agent-marketplace#235` renders it into the opened PR under `## Changelog`; omitted or unrecognised, the field is simply ignored on that side. The whole payload (including the pre-existing `tags` array) is built with `jq -n` rather than spliced into the old unquoted `curl -d @- <<EOF` heredoc — a multi-line changelog containing backticks, quotes or newlines would break that pattern and silently drop the entire dispatch, the same class of bug that already hit this repo's own `tags` field once (`agent-marketplace@89aa850`). There is no `dispatch.yml` in this repo to mirror the change into.

A failed release is never "fixed" in place — "Fail if tag already exists" refuses to reuse a version number, so a failure's only way forward is the next version number. Nothing here tries to detect or special-case a retry, and nothing should.

## Optional Codex review augmentation lives in the reviewer

When the Codex plugin is installed and ready, `agents/reviewer.md` runs `scripts/codex-review.mjs` (read-only, never `--write`) and folds blocking findings into its verdict; every failure degrades silently to the reviewer's own review with a visible `[nit]` so the orchestrator can see the pass did not run. Codex is therefore recommended, **not** declared under `dependencies`. The pass runs on every review round, including re-reviews.

## Provider-portability gotchas

`Closes #<n>` auto-links on GitHub/GitLab; Azure DevOps uses `AB#<n>`. `list_pipeline_runs` / `get_pipeline_run` / `get_pipeline_step_log` normalize providers, but `conclusion == "success"` is the GitHub vocabulary the skill checks — extend the check when targeting another provider.
