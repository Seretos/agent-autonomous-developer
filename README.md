# agent-python-developer-ticket-workflow

A Claude Code **skill + agents** plugin that turns [agent-project-issues](https://github.com/Seretos/agent-project-issues)
tickets into draft pull requests for **Python** projects — single tickets end-to-end, or a
whole backlog dispatched in parallel across isolated git worktrees.

Ships **only skill/agent content** — no binaries, no MCP server of its own. It drives two
other plugins' MCP servers (see [Dependencies](#dependencies)).

## What it does

Two skills, split into two lanes that never overlap:

| Skill | Runs from | Does |
|---|---|---|
| **orchestrate-tickets** | the **main** checkout | Picks a conflict-free set of open tickets (via the `conflict-analyst` subagent — disjoint file footprints), creates one git worktree per ticket, and starts one idle background Claude session per worktree. Implements nothing itself. |
| **process-ticket** | inside a **worktree** on a feature branch | Runs one ticket end-to-end through five subagents — `context-extractor → planner → developer → reviewer` — and ends with a pushed feature branch + an open **draft** PR and traceability comments on the ticket. |

The five subagents (`agents/`): `conflict-analyst`, `context-extractor`, `planner`,
`developer`, `reviewer`. Each has a narrow, mostly read-only scope; only `developer` edits code.

## Dependencies

This plugin is inert without two MCP plugins enabled **in the consuming session**:

```json
// .claude/settings.json (or settings.local.json) of the target project
"enabledPlugins": {
  "agent-python-developer-ticket-workflow@agent-marketplace": true,
  "agent-project-issues@agent-marketplace": true,
  "agent-worktree@agent-marketplace": true
}
```

- **agent-project-issues** — ticket/PR/comment operations (`get_ticket`, `list_tickets`,
  `list_comments`, `get_pr`, `add_comment`, `create_pr`, …).
- **agent-worktree** — git-worktree lifecycle (`worktree_create`, `worktree_remove`, …).

These are declared in `.claude-plugin/plugin.json` under `dependencies`, but the marketplace
registry does not auto-install them today — enabling them is the consumer's responsibility.

## Install

```
/plugin marketplace add Seretos/agent-marketplace
/plugin install agent-python-developer-ticket-workflow@agent-marketplace
```

Then enable the two MCP dependencies as shown above.

## Usage

From the **main** checkout of a Python project registered in agent-project-issues:

```
orchestrate tickets in <project>            # all open tickets
orchestrate ticket 7 in <project>           # one ticket
```

It creates the worktrees and starts idle background sessions. In each session you then run:

```
/reload-plugins        # fresh worktree sessions don't auto-load plugin MCPs
process ticket #7 in <project>
```

> **Scope:** Python projects (the worker agents assume `python -m pytest` and a `src/`
> layout). The project id is **not** auto-detected — pass it explicitly (`… in <project>`).

## Branches

- `main` — source of truth.
- `release` — orphan branch, force-pushed by `release.yml`; install-ready files only
  (`.claude-plugin/plugin.json`, `skills/`, `agents/`, `README.md`).

## Release

```
Actions → release → Run workflow → version=X.Y.Z
```

Stamps the version into `plugin.json` (CI only — never hand-bump it), pushes the orphan
`release` branch, tags `agent-python-developer-ticket-workflow--vX.Y.Z`, and dispatches to
`Seretos/agent-marketplace` (category `skill`) via `MARKETPLACE_DISPATCH_TOKEN`.
