Automates the journey from open ticket to draft pull request for projects in any language (stack auto-detected). Instead of manually reading a ticket, planning changes, writing code, and opening a PR, you invoke one skill and five specialised subagents handle the work end-to-end — or dispatch an entire backlog, wave by wave, across isolated git worktrees.

Key capabilities:

- **Wave-based backlog dispatch** — `orchestrate-tickets` analyses your open tickets for file conflicts and unmet dependencies, lays the safe ones out into ordered parallel-safe waves, then creates one git worktree per ticket and runs each wave's tickets through sequentially, so no ticket's changes ever interfere with another's.
- **Five-subagent pipeline** — `process-ticket` runs `conflict-analyst → context-extractor → planner → developer → reviewer` in sequence: gathers context, writes a plan, implements the code with tests, reviews for correctness, then pushes a feature branch and opens a draft PR with traceability comments on the ticket.
- **Optional Codex review augmentation** — if the Codex plugin is installed and ready, the reviewer automatically adds a Codex correctness pass (via the bundled `scripts/codex-review.mjs`) and folds its blocking findings into the verdict; no setup required.
- **Optional Serena navigation** — if the agent-serena-wrapper plugin is installed, the subagents gain symbol-aware navigation and editing tools for more precise, token-efficient code exploration; falls back to standard file tools without it.
- **Draft-PR output with traceability** — every run ends with a pushed feature branch, an open draft PR, and comments linking the PR back to the originating ticket.
