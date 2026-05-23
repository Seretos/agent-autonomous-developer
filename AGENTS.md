# agent-python-developer-ticket-workflow — architecture & conventions

Pure skill + agents plugin. No binary, no MCP server. It orchestrates a ticket→draft-PR
workflow for **Python** projects on top of the `agent-project-issues` and `agent-worktree`
MCPs.

## Layout

```
skills/
  orchestrate-tickets/SKILL.md   # fleet orchestrator — runs only on the main checkout
  process-ticket/SKILL.md        # per-ticket pipeline — runs only inside a worktree
agents/
  conflict-analyst.md            # picks a conflict-free parallel set (read-only)
  context-extractor.md           # distills a ticket into a context summary (read-only)
  planner.md                     # grounded plan + question-loop (read-only)
  developer.md                   # implements the plan + runs pytest (edits code)
  reviewer.md                    # reviews the diff (read-only)
.claude-plugin/plugin.json       # manifest + dependencies on the two MCP plugins
.github/workflows/
  lint.yml                       # plugin.json + skill/agent frontmatter validation
  release.yml                    # manual-dispatch release flow
```

## The two-lane model (load-bearing)

`orchestrate-tickets` and `process-ticket` guard mutually-exclusive lanes so a fleet and its
workers never step on each other:

- **orchestrate-tickets** runs **only** from the main checkout (`HEAD` == default branch and
  `git-dir` == `git-common-dir`). It creates worktrees and launches idle background sessions.
- **process-ticket** runs **only** inside a linked worktree on a feature branch (the inverse
  guard). It implements, pushes, and opens the draft PR.

Each skill enforces its own guard up front and STOPs if it's in the wrong lane.

## Conventions a contributor must preserve

- **Project id is a parameter, never hardcoded.** There is no cwd→project auto-resolution in
  agent-project-issues (`local_path` is null, `source: config`). The skills take the project
  id as an argument (`… in <project>`); if absent, resolve it via `find_projects` and confirm.
  The orchestrator threads the id into every subagent prompt — agents never assume a fixed id.
- **Python stack assumptions.** The worker agents assume `python -m pytest` (and
  `pip install -e ".[test]"` if deps are missing) and a `src/` layout. This is intentional —
  the plugin is Python-scoped (the name says so). Keep stack specifics in the worker agents,
  not smeared across the skills.
- **`Closes #<n>` is a GitHub/GitLab convention.** The draft-PR body uses it for auto-linking.
  It is **not** portable to Azure DevOps (`AB#<n>`) or Jira. If this plugin ever targets those
  providers, the close-keyword must become provider-aware.
- **Ticket statuses are provider-native.** Never hardcode status strings — use
  `list_ticket_statuses` for the project before any `update_ticket`.
- **Worktree lifecycle goes through the agent-worktree MCP.** Do **not** fall back to raw
  `git worktree add` — that creates worktrees the MCP can't list/remove/reconcile. If the MCP
  isn't loaded in the session, hard-fail and tell the user to `/reload-plugins`.
- **Stateless teardown.** When tearing a worktree down, **stop the background Claude session
  first** (it locks the directory on Windows), then `worktree_remove`. Resolve the session
  from the orchestrator's own launch history or by matching the worktree path to a running
  bg job — never persist a state/sidecar file.
- **Worktree directory names** are derived independently from the branch name (the
  `fix/<n>-<slug>` convention contains a `/`).

## Release / versioning

Version is stamped from the workflow-dispatch input in CI only; the `version` in
`plugin.json` on `main` stays a placeholder and is **never** hand-bumped. Tag format:
`agent-python-developer-ticket-workflow--vX.Y.Z`. Marketplace registration happens via the
`plugin-release` dispatch (category `skill`).
