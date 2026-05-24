# agent-python-developer-ticket-workflow — architecture notes

Pure skill + agents plugin (no binary, no MCP). Drives a ticket→draft-PR workflow for
**Python** projects on top of the `agent-project-issues` and `agent-worktree` MCPs.

README.md covers *what* it does, install, and release. The skills/agents document their own
rules. This file records only the non-obvious decisions a contributor must not silently break
— the cross-file invariants and rationale you can't reconstruct from any single file.

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

## Python scope lives in the worker agents

The plugin is Python-scoped by name. Stack assumptions (`python -m pytest`, `src/` layout,
`pip install -e ".[test]"`) belong in the worker agents (`developer`), **not** smeared across
the orchestrating skills — keep the skills stack-neutral so the scope stays in one place.

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
the same reason the Python stack scope does (one place, not smeared across the skill).

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

## Provider-portability gotchas

The draft-PR flow assumes GitHub/GitLab conventions that are **not** portable to Azure DevOps
or Jira:

- `Closes #<n>` auto-linking in the PR body (Azure DevOps uses `AB#<n>`, Jira differs).
- Ticket status strings are provider-native — resolve them via `list_ticket_statuses` for the
  project, never hardcode.

Make both provider-aware before targeting another backend.
