# Plan — fixture#122-shape: prose-executed requirement

## Goal
The planner declares a requirement whose only executor is a model reading a
prose file as `none`, with its decidable part extracted into a script.

## Approach
- `agents/planner.md` gains a rule; `scripts/critic/prose-role-check.py`
  classifies the diff hunks by role.

### Affected files
Modified: `agents/planner.md`.
New: `scripts/critic/prose-role-check.py`, `tests/test_prose_role_check.py`.

### Test / verification strategy
Symptom (verbatim from ticket): "No available assertion executes such a requirement; any assertion is a string comparison. The two gates then demand opposite things, and the run ends `blocked` with no replan left."

R1. Hunk classification by role — `driving-test`.
  - Behaviour: a diff is classified per hunk PROSE or CODE by role.
  - Driving test: `tests/test_prose_role_check.py` runs the script over a
    synthesised diff and asserts the exit code and a line per hunk.

R2. The planner declares prose-executed requirements as `none` — `none`.
  Prose-executed: agents/planner.md — decidable part extracted into
  scripts/critic/prose-role-check.py, covered by tests/test_prose_role_check.py
