# fixture#122-shape — a rule that only a model reading a prose file executes

**Type:** Bug

## Description

A requirement's only executor is a model reading a prose file
(`agents/planner.md`). No available assertion executes such a requirement;
any assertion is a string comparison. The two gates then demand opposite
things, and the run ends `blocked` with no replan left.
