# Fixed project constraints

These are stable facts about how the project the plan is written for is worked on. They are
included in every review package unchanged. They are context for judging the plan, not
requirements the plan is measured against — the specification above is what the plan is measured
against.

- The project's technology stack is not fixed by this document: it is auto-detected from the
  repository at the start of the work, and the plan is expected to name the concrete test command
  it will use. Do not assume any particular language, framework or tooling beyond what the plan and
  the specification state.
- Every behavioural change is implemented test-first: a driving test written and failing for the
  right reason before the production code exists, passing afterwards. A plan is expected to say
  what will prove each behaviour, at a level a test designer can work from — not to enumerate
  concrete test cases itself.
- An implementation plan is expected to state: the goal, the approach, the affected files (new and
  modified), and the test-verification strategy.
- The specification is the ticket: its title, body and comments. For an epic it is the epic plus
  all of its child tickets. Comments may refine or overrule the body; where they conflict, the later
  comment is the current reading unless the scope statement says otherwise.
- The plan is judged against the scope stated below, not against everything the ticket touches on.
  A plan is not incomplete merely because it does not restate the ticket, and a requirement the
  scope statement explicitly excludes is not a gap.
