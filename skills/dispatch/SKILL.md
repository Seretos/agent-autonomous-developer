---
name: dispatch
description: Entry-point for all autonomous ticket work — orchestrating a fleet or processing a single ticket. Detects which lane you are in (main checkout vs. worktree feature branch) and loads the right skill automatically. Use for any of: "orchestrate tickets", "process ticket #N", "run all open tickets", "split tickets", "re-slice epics".
---

# dispatch — lane-aware entry point

You are a thin dispatcher. Your only job is to run a deterministic git lane check
and immediately invoke the correct backing skill. You do no ticket work yourself
and make no MCP calls.

## Lane check

Run these two commands:

```
git rev-parse --git-dir
git rev-parse --git-common-dir
```

Capture both outputs (trim any trailing whitespace). Then:

- **GIT_DIR == GIT_COMMON_DIR** → you are in the **main checkout** →
  invoke `Skill(skill="orchestrate-tickets")`, passing all user-supplied text
  verbatim. The backing skill parses the ticket number and project id itself.

- **GIT_DIR != GIT_COMMON_DIR** → you are in a **linked worktree** on a
  feature branch → invoke `Skill(skill="process-ticket")`, passing all
  user-supplied text verbatim.

- **git fails** (not a git repository, command unavailable, non-zero exit) →
  report the error and stop. Do not guess which lane you are in.

## That is all

Do nothing else — no phase logic, no MCP calls, no state. Delegate immediately
after the lane check.

---

> **Why this exists.** Both `orchestrate-tickets` and `process-ticket` carry
> `disable-model-invocation: true` — the model will not auto-select them. This
> dispatcher is the sole model-invocable entry point; it performs the deterministic
> lane check so the model never has to guess from description text. Power users can
> still bypass the dispatcher and invoke either backing skill directly via
> `/orchestrate-tickets` or `/process-ticket`.
