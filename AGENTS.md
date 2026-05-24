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

## Provider-portability gotchas

The draft-PR flow assumes GitHub/GitLab conventions that are **not** portable to Azure DevOps
or Jira:

- `Closes #<n>` auto-linking in the PR body (Azure DevOps uses `AB#<n>`, Jira differs).
- Ticket status strings are provider-native — resolve them via `list_ticket_statuses` for the
  project, never hardcode.

Make both provider-aware before targeting another backend.
