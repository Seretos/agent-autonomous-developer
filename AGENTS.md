# agent-autonomous-developer — architecture notes

Pure skill + agents plugin (no binary, no MCP). Drives a ticket→draft-PR workflow for
projects in **any language** (stack auto-detected) on top of the `agent-project-issues`
and `agent-worktree` MCPs.

README.md covers *what* it does, install, and release. The skills/agents document their own
rules. This file records only the non-obvious decisions a contributor must not silently break
— the cross-file invariants and rationale you can't reconstruct from any single file.

## Tool priority

Skills and MCP tools take priority over raw file tools — and this **explicitly overrides** the generic harness default that says "prefer the dedicated file/search tools (Glob/Grep/Read)". When a skill or MCP tool covers the task, reach for it first; fall back to raw Glob/Grep/Read only when none applies.

Concretely: any *"where is X defined / what does the code support / which Y exist / how does X work / find the callers of X"* question is a **code-understanding task → use the matching skill first** (e.g. the `serena-wrapper` symbol-aware tools), never raw Glob/Grep/Read.

## Two-lane invariant (cross-file)

`orchestrate-tickets` runs **only** on the main checkout; `process-ticket` runs **only**
inside a linked worktree on a feature branch. Each enforces a mirror-image guard (`HEAD`
plus `git-dir` vs `git-common-dir`). They are a **matched pair**: if you touch one lane's
guard, change the other's to match — otherwise a fleet and its workers can land in the same
lane and collide. Neither skill knows about the other's guard, so this pairing lives here.

## Why the project id is always a parameter

agent-project-issues does not resolve cwd→project (`local_path` is null, `source: config`),
so there is no auto-detection to fall back on. Both skills take the project id as an explicit
argument and thread it through every subagent prompt and MCP call. Don't add a "guess the
project from cwd" shortcut — there's nothing to guess from.

## Stack auto-detection lives in the planner + developer

The plugin is language-agnostic. Stack assumptions are **detected from the project's config
files** (`pyproject.toml` → `python -m pytest`, `package.json` → `npm test`/`jest`/`vitest`,
`go.mod` → `go test`, `Cargo.toml` → `cargo test`, `pom.xml`/`build.gradle` → maven/gradle,
…) rather than hardcoded. The **planner** detects the stack and pins the concrete
test/install/build commands in the plan's test strategy; the **developer** executes *those*
commands (and re-derives them from the config if the plan is thin). Keep the orchestrating
skills stack-neutral — the scope stays in these two worker agents, in one place.

## Test adequacy is a three-agent chain

Tests aren't merely "written" — adequacy is enforced across three agents, and weakening any
one link drops the guarantee:

- **planner** mandates the strategy: a regression test that reproduces the reported problem,
  the edge cases, and a test for every behavioural change.
- **developer** writes them (the regression test red→green first) and reports what each asserts.
- **reviewer** makes coverage a **`[blocking]` gate** — a missing regression test, an untested
  behavioural change, or an uncovered edge case is `CHANGES_REQUESTED`.

Enforcement rides the existing one-round fix loop in `process-ticket`: a blocking coverage
finding sends the developer back to add the test, then the reviewer re-checks. There is
deliberately **no separate test phase/agent** — test scope stays in these worker agents for
the same reason the stack-detection scope does (one place, not smeared across the skill).

## Optional Codex review augmentation lives in the reviewer

When the Codex plugin (`openai/codex-plugin-cc`) is installed and ready, the `reviewer`
agent runs an **extra** Codex correctness pass and folds Codex's blocking findings into its
`VERDICT`. A few non-obvious decisions:

- **It lives in the `reviewer` agent, not in `process-ticket`.** The agent already owns the
  `VERDICT: APPROVE / CHANGES_REQUESTED` contract, so the skill and its one-round fix loop stay
  untouched — same as keeping stack scope in the worker agents.
- **Presence-driven, no flag.** Detection = glob the Codex companion script under
  `~/.claude/plugins/cache/<marketplace>/codex/<version>/scripts/codex-companion.mjs`, then
  gate on `codex-companion.mjs setup --json` returning `ready: true`. No opt-in setting.
- **Why a direct `Bash` call to the companion script, not `/codex:review`.** That slash command
  is `disable-model-invocation: true` (user-typed only) and subagents have no `Skill`/`Agent`
  tool — so the only programmatic entry is `node "<script>" review --wait`. `--write` is never
  passed: Codex must stay review-only, like the reviewer.
- **Fragile bit.** The cross-plugin path discovery depends on the cache layout above; if the
  marketplace/plugin dir names change, discovery returns nothing and the reviewer **degrades
  silently** to its built-in review (never a hard error).
- **Teardown coupling (cross-file).** The Codex pass spawns an `app-server-broker.mjs` helper
  that can **outlive** its `--bg` session — it isn't a daemon-tracked job, so `claude stop`
  doesn't reach it. `orchestrate-tickets` teardown must force-kill that broker **before**
  `worktree_remove`, or on Windows the worktree dir stays locked, the remove half-completes,
  and the agent-worktree MCP state desyncs into an unremovable phantom entry. If you change how
  the reviewer launches Codex (process name or `--cwd`), update the teardown matcher in
  `skills/orchestrate-tickets/SKILL.md` to match.

## Long-lived process guardrail (cross-file)

`agents/developer.md` carries the rule: before starting any process that does not exit on its
own (daemon, dev-server, watcher, GUI editor, etc.), the developer must use `worktree_start`
with an appropriate `start:` contract step so the process is tracked and killed automatically
on worktree teardown. When no suitable contract step exists and an ad-hoc launch is
unavoidable, the developer must emit an explicit warning in the change report that the process
will survive worktree teardown and must be terminated manually.

The rule is **generic and app-agnostic by design** — no concrete tool or application is named
as a prescriptive target. App-specific variants (e.g. how to handle a Unity GUI editor) belong
in wrapper projects such as `agent-unity-wrapper`, not in this plugin.

**Invariant for contributors:** if you change the developer's process-launch guidance, verify
that the updated rule still covers **both** branches — (1) the tracked-start path
(`worktree_start` + `start:` contract step) and (2) the manual-warning fallback for ad-hoc
launches — and update this note to stay consistent with the new wording.

## Why ticket-slicing knowledge lives in the orchestrator, not a standalone skill

Slicing recommendations are **model-relative** — only meaningful for the isolated-worker
model that `orchestrate-tickets` implements. A recommendation like "merge tickets #3 and #7
into one vertical slice" is sound advice for this plugin's model (one worktree, one worker,
no shared context) but would be wrong advice for a future `autonomous-teams` shared-context
model, where workers share working memory and can therefore coordinate on horizontally-cut
tickets without reconvergence pain.

Splitting slicing into a standalone `slice-tickets` skill would decouple the recommendation
from the execution model it describes. Changes to the orchestration model would require
updating both files in lockstep — a coordination burden with no benefit, and a source of
stale guidance when one file is updated and the other isn't. The `conflict-analyst` is the
natural home for fit assessment because it already reads all tickets, grounds footprints in
code, and has full access to the dependency graph; fit assessment is a natural extension of
that analysis, not a separate concern.

A future `autonomous-teams` shared-context model would require different slicing heuristics
(horizontal cuts become viable; wave-width and cross-wave file sharing matter less). Those
heuristics belong with that model's orchestrator — not here — for the same reason: keeping
recommendation and model co-located makes both easier to keep correct.

There is deliberately **no standalone `slice-tickets` skill** in this plugin. Do not create
one.

## Provider-portability gotchas

The draft-PR flow assumes GitHub/GitLab conventions that are **not** portable to Azure DevOps
or Jira:

- `Closes #<n>` auto-linking in the PR body (Azure DevOps uses `AB#<n>`, Jira differs).
- Ticket status strings are provider-native — resolve them via `list_ticket_statuses` for the
  project, never hardcode.

Make both provider-aware before targeting another backend.
