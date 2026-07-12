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
| **orchestrate-tickets** | the **main** checkout | Drives the whole run: lays out open tickets into an ordered set of parallel-safe **waves** (via the `conflict-analyst` subagent — disjoint file footprints **and** no unmet "must come after" dependency stated in a ticket; the rest are deferred, tagged `file-collision` or `logical-dependency`), then executes wave-by-wave against one shared **integration branch** — see below. |
| **process-ticket** | inside a **worktree** on a feature branch | Runs one ticket end-to-end through four subagents — `context-extractor → planner → developer → reviewer` — committing locally. In `solo` mode (direct/manual invocation) it also pushes its own branch and opens its own draft PR; in `integration` mode (driven by `orchestrate-tickets`) it leaves the push/PR/ticket-comment to the caller. |

The five subagents (`agents/`): `conflict-analyst`, `context-extractor`, `planner`,
`developer`, `reviewer`. Each has a narrow, mostly read-only scope; only `developer` edits code.

### The wave-based fleet run

`orchestrate-tickets` no longer stops after handing off a batch of worktrees for the user to
drive by hand — it runs the whole fleet to completion:

1. Creates one shared **integration branch** (`integration/<run-slug>`) off the refreshed
   default branch, and pushes it once.
2. Asks the `conflict-analyst` for an ordered `waves` array (DAG-layered parallel-safe sets),
   or synthesizes a single one-member wave for a single ticket.
3. For each wave, **sequentially**: creates that wave's worktrees off the integration branch's
   **current head** (not the default branch — only the integration branch itself branches off
   that), then runs `process-ticket(mode=integration)` **in parallel** across the wave's
   members.
4. Merges every approved-and-green member into the integration branch with `git merge --no-ff`,
   then runs the project's **full test suite** on the integration branch as a cross-wave
   integration gate.
   - **Green** → tears down the wave's worktrees, pushes the integration branch, and moves on
     to the next wave.
   - **Red** → **stops immediately, with no automatic revert.** The failed wave's merge stays
     local and unpushed, its worktrees are left intact for inspection, and every already-pushed
     prior wave is left untouched. Resolving it is the user's call.
5. Once every wave is processed, opens **exactly one** combined draft PR (`head` = the
   integration branch) with `Closes #<n>` for every ticket that landed, and comments once per
   ticket.

A single ticket still goes through the identical pipeline — SINGLE mode is just a one-member,
one-wave run, so it gets the same safety gates without any of the fleet ceremony mattering.

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

This runs the whole fleet automatically — wave by wave, against one shared integration
branch — and ends with a single combined draft PR. There is nothing to run by hand in each
worktree; `process-ticket` is invoked for you, per wave member, in `mode=integration`.

To drive a single worktree yourself instead (bypassing the fleet, e.g. for a one-off manual
fix on a branch/worktree you prepared outside this flow), run `process-ticket` directly in
`solo` mode:

```
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
