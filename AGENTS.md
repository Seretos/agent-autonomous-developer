# agent-autonomous-developer

Pure skill + agents plugin (no binary, no MCP). Takes **one work package** — a ticket, or an epic standing for all its child tickets — from a prepared worktree to a pull request with a **green CI pipeline**, for projects in any language (stack auto-detected), on top of the `agent-project-issues` MCP.

README.md covers *what* it does, install, and release. The skill and the agents document their own rules. This file records only the non-obvious decisions a contributor must not silently break — the cross-file invariants and the rationale you cannot reconstruct from any single file.

## Tool priority

Skills and MCP tools take priority over raw file tools — and this **explicitly overrides** the generic harness default that says "prefer the dedicated file/search tools (Glob/Grep/Read)". When a skill or MCP tool covers the task, reach for it first; fall back to raw Glob/Grep/Read only when none applies.

## Scope: one package in, one green PR out — nothing above that

This plugin has exactly one skill, `process-ticket`, and it is not model-invocable: the caller is a headless `claude -p` session started by an orchestrator (in the Seretos ecosystem, `agent-ticket-orchestrator`), or a human typing the slash command in a worktree. The plugin knows **nothing** about boards, ticket selection, bundling, worktree lifecycle, or other packages. It used to carry a fleet layer (`orchestrate-tickets`, wave scheduling, a `dispatch` lane router, a `conflict-analyst`); all of that moved up and out in the 2026-08 rebuild, for a reason that is still load-bearing: parallelism inside one repository bought nothing and cost the entire B6 liveness apparatus, while a lower plugin that knows about the board cannot be reused by a caller with a different board. Do not add ticket selection, column writes, or multi-package logic here.

## The contract with the caller is a write obligation, not a return schema

A headless dispatch returns "process ended" plus text. That channel is structurally too poor to carry state, and a caller that reconstructs state from prose is a bug waiting to happen. So `process-ticket` owes the caller a **fixed set of comment events** on the package ticket (`<!-- adev:event v1 … -->`, names and fields in `skills/process-ticket/SKILL.md` → "Events"). The caller derives everything from the latest event. Three invariants follow:

- The event vocabulary is **closed**. Adding an event is a contract change; tell the caller's maintainers (`agent-ticket-orchestrator/AGENTS.md` carries the same table).
- Exactly **one terminal event** per run (`ci-green`, `blocked`, `failed`), posted last, then the turn ends. A run that keeps working after a terminal event makes the caller act on a stale state.
- The `rounds:` line must distinguish findings rounds (`f`) from infrastructure rounds (`i`). A human who reads a `failed` event has to be able to tell "three real critiques" from "three crashes" — they are different problems with different fixes.

## There is no human in this process, by construction

The dispatching CLI passes `--disallowedTools AskUserQuestion`, and no agent definition here grants it. A question is a **`blocked` event** and the end of the run. Before posting one, `process-ticket` must have tried to answer from the package transcript (epic body, sibling tickets, prior comments, the code the planner cites) and must say in the event what it checked and why that was not enough — escalating is not forwarding. The human is asked for a **decision**, never for a **retry**: anything whose answer would be "try again" is covered by the round caps. A `blocked` event whose only sensible reaction is "kick it again" is a bug in this plugin.

## Every Agent dispatch is unnamed, synchronous, fresh

A named `Agent(...)` spawn delivers on a `SendMessage` mailbox nothing here listens to; the caller waits for a task-notification that never comes (`#60`, `#88`). Resuming an existing agent via `SendMessage` is the same channel by another name. Every round trip — planner answer rounds, critic rounds, developer fix rounds, re-reviews, CI repairs — is a **fresh unnamed `Agent(..., run_in_background: false)` call with everything re-inlined** (plan, findings, prior change report). Subagents cannot refetch. The same rule is ecosystem-wide (root `AGENTS.md`); this plugin is where it was learned.

The same non-suspension applies one level down, inside a single developer dispatch: a subagent that ends its turn while it backgrounded a shell command does not get suspended and later resumed either — the harness kills the background process and the turn's "I'll resume once it completes" is never honored (ticket `#93`, a live recurrence of the exact failure mode `#83`/`#88` already fixed at the fleet layer, this time inside a single dispatch). `agents/developer.md`'s prose Hard Rule forbidding this was already in place when `#93` happened — a live incident proved prose alone is not reliable enough — so it now has a mechanical backstop: the `SubagentStop` hook `hooks/check-developer-background-wait.mjs` (wired in `hooks/hooks.json`, matcher `developer`) scans the developer's own transcript for a `Bash(run_in_background: true)` call with no later `Monitor` call and blocks the stop. **Keep the hook and the Hard Rule in sync** — if the sanctioned wait pattern in `agents/developer.md` step 4 changes (a different tool than `Monitor`, a different resolution than "background + wait in-turn"), the hook's detection logic must change with it, or it will either stop catching the real anti-pattern or start false-blocking a legitimate pattern.

## CI is the verdict; the local suite is a pre-filter

The developer still runs the full suite locally (backgrounded `nohup` + in-turn `Monitor`; see `agents/developer.md`) because it is cheaper to fix locally than on the runner. But the event for it says `tests-green` with "local pre-filter only", and the only success event is `ci-green`. Two reasons: local runs crash regularly on this platform, and a CI result was produced by nobody with a stake in the outcome — the same argument as critic isolation, applied to tests.

Polling the pipeline (`list_pipeline_runs(commit_sha=HEAD)` + `Bash("sleep 60")`) happens in **`process-ticket`'s own turn**, never inside a subagent: a subagent's background processes die with its turn and its task-notifications go to the parent, which is exactly the silent stall `#88` documented. The 45-minute cap per CI round counts as an infrastructure round when hit.

## Critic isolation is a property of the process, not of the prompt

`plan-critic` and `test-critic` (`agents/`) are ordinary subagents, but the critique itself runs in separate `claude -p` processes started by `scripts/critic/*-run.sh` with `--setting-sources "" --strict-mcp-config --disable-slash-commands --tools "" --system-prompt <file> --json-schema <file>`, cwd a `mktemp -d` **outside** the repository (CLAUDE.md discovery walks parent directories; a subdirectory of the repo would defeat the isolation). The review package is assembled by a script from verbatim inputs — the ticket transcript, the plan, the test diff — because the curator of a package is the one role that could defang a critique. The merge (`plan-critic-merge.py`) is deterministic code with no model in it: a model between the critics and the decision would be a curator again. `check-critic-isolation.sh` runs as a static pre-flight on every gate invocation; run it with `--live` after every CLI upgrade.

A critic has no repository access. Its claims about existing code are `unverified-assumption` findings, and **`process-ticket` never upgrades them to defects** — the planner, which could see the code, is trusted over a critic that could not.

Ported from the `sothis` project's gates (2026-08); the flag set is identical across both runners on purpose, and `check-critic-isolation.sh` refuses to run if one runner drops a flag the other keeps.

## Three-round caps: one rule, four applications

plan-critic, test-critic, review, and CI each cap at three rounds, with a package ceiling of nine gate rounds (CI excluded). `process-ticket` counts; a critic never counts its own rounds. An infrastructure-failed round counts — exempting it would turn the cap into an unbounded retry loop. The reviewer formerly had one fix cycle and no defined path for "still blocking after it"; that gap is closed by the same cap and `failed`.

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

## Optional Codex review augmentation lives in the reviewer

When the Codex plugin is installed and ready, `agents/reviewer.md` runs `scripts/codex-review.mjs` (read-only, never `--write`) and folds blocking findings into its verdict; every failure degrades silently to the reviewer's own review with a visible `[nit]` so the orchestrator can see the pass did not run. Codex is therefore recommended, **not** declared under `dependencies`. The pass runs on every review round, including re-reviews.

## Provider-portability gotchas

`Closes #<n>` auto-links on GitHub/GitLab; Azure DevOps uses `AB#<n>`. `list_pipeline_runs` / `get_pipeline_run` / `get_pipeline_step_log` normalize providers, but `conclusion == "success"` is the GitHub vocabulary the skill checks — extend the check when targeting another provider.
