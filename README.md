<img src="assets/icon.png" alt="agent-autonomous-developer icon" width="96" />

# agent-autonomous-developer

A Claude Code **skill + agents** plugin that turns [agent-project-issues](https://github.com/Seretos/agent-project-issues)
tickets into draft pull requests for projects in **any language** — single tickets end-to-end, or a
whole backlog dispatched in parallel across isolated git worktrees.

Ships **only skill/agent content** — no binaries, no MCP server of its own. It drives two
other plugins' MCP servers (see [Dependencies](#dependencies)).

## What it does

Three skills: one model-facing dispatcher that routes to two lane-specific backing skills:

| Skill | Runs from | Does |
|---|---|---|
| **dispatch** | anywhere | Model-facing entry point. Normally selected automatically by the model; runs a git lane check and routes to the right skill. To invoke a backing skill directly, use `/orchestrate-tickets` or `/process-ticket`. |
| **orchestrate-tickets** | the **main** checkout | Picks a parallel-safe set of open tickets (via the `conflict-analyst` subagent — disjoint file footprints **and** no unmet "must come after" dependency stated in a ticket; the rest are deferred, tagged `file-collision` or `logical-dependency`), creates one git worktree per ticket, and starts one idle background Claude session per worktree. Implements nothing itself. |
| **process-ticket** | inside a **worktree** on a feature branch | Runs one ticket end-to-end through five subagents — `context-extractor → planner → developer → reviewer` — and ends with a pushed feature branch + an open **draft** PR and traceability comments on the ticket. |

The five subagents (`agents/`): `conflict-analyst`, `context-extractor`, `planner`,
`developer`, `reviewer`. Each has a narrow, mostly read-only scope; only `developer` edits code.

> **Optional Codex review.** If the [Codex plugin](https://github.com/openai/codex-plugin-cc)
> is installed and logged in, the `reviewer` automatically adds a Codex correctness pass and
> folds its blocking findings into the verdict. Without Codex, the review step runs exactly as
> before — no setup required either way.

> **Optional Serena navigation.** If the [agent-serena-wrapper](https://github.com/Seretos/agent-serena-wrapper)
> plugin is installed, the `process-ticket` subagents (`context-extractor`, `planner`,
> `developer`, `reviewer`) automatically gain access to Serena's symbol-aware navigation and
> editing tools (`find_symbol`, `find_implementations`, `replace_symbol_body`, etc.) for more
> precise, token-efficient code exploration and edits. Without `agent-serena-wrapper`, behaviour
> is unchanged — the unresolved tool names are silently dropped by Claude Code, and the
> subagents fall back to `Read`/`Glob`/`Grep`/`Edit`/`Write` as before. No hard dependency.

## Dependencies

This plugin is inert without two MCP plugins enabled **in the consuming session**:

```json
// .claude/settings.json (or settings.local.json) of the target project
"enabledPlugins": {
  "agent-autonomous-developer@agent-marketplace": true,
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
/plugin install agent-autonomous-developer@agent-marketplace
```

Then enable the two MCP dependencies as shown above.

## Usage

From the **main** checkout of a project registered in agent-project-issues:

```
orchestrate tickets in <project>            # all open tickets
orchestrate ticket 7 in <project>           # one ticket
```

It creates the worktrees and starts idle background sessions. In each session you then run:

```
/reload-plugins        # fresh worktree sessions don't auto-load plugin MCPs
process ticket #7 in <project>
```

> **Scope:** any language — the worker agents **auto-detect** the project's stack and test
> command (`python -m pytest`, `npm test`, `go test`, `cargo test`, …) from its config files.
> The project id is **not** auto-detected — pass it explicitly (`… in <project>`).

## Branches

- `main` — source of truth.
- `release` — orphan branch, force-pushed by `release.yml`; install-ready files only
  (`.claude-plugin/plugin.json`, `skills/`, `agents/`, `README.md`).

## Release

```
Actions → release → Run workflow → version=X.Y.Z
```

Stamps the version into `plugin.json` (CI only — never hand-bump it), pushes the orphan
`release` branch, tags `agent-autonomous-developer--vX.Y.Z`, and dispatches to
`Seretos/agent-marketplace` (category `skill`) via `MARKETPLACE_DISPATCH_TOKEN`.
