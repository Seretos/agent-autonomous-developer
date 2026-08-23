#!/usr/bin/env bash
#
# Assembles the review package handed to one isolated critic.
#
# Assembly is a script rather than a writing task on purpose. The curator of a review package is
# the one role that could quietly defang the critique — by paraphrasing a requirement, or by
# leaving out the section a plan is weakest against. So the sources are fixed here and copied
# verbatim, and the curating agent contributes only the scope pointer and the plan itself. What
# the critic sees is therefore reproducible from the inputs, and the package file stays on disk
# for anyone who wants to check that.
#
# The full specification is included, never a selection of "relevant" sections: selection is the
# omission risk, and the critic has no repository access to make up for anything left out. It also
# lets the critic notice a plan claiming work that the specification assigns to a different system.
#
# The specification here is the TICKET PACKAGE: the verbatim title, body and comments of the ticket
# and, for an epic, of every child ticket. The dispatching skill assembles that file from the
# tracker without editing it; this script copies it whole. There is no repository-root argument,
# by contrast with the sothis original this was ported from, because nothing in the package is
# read out of the repository.
#
# THE LENS
#
# The gate runs three critics, not one. They are identical in every respect that matters —
# same isolation, same specification, same constraints, same scope, same plan, same system prompt
# — and differ only in a single fixed focus block appended as PART 5. That is what makes the three
# results comparable and the packages diffable: run this script three times with the same inputs
# and different lens ids, and `diff` shows PART 5 and nothing else.
#
# The lens texts live in this script, hardcoded, and the caller may only name one of the ids below.
# An agent choosing or authoring its own focus would put the curator back into a pipeline built to
# have none: the easiest way to defuse a critique is to aim it somewhere harmless.
#
# Usage: plan-critic-package.sh <spec-file> <scope-file> <plan-file> <lens-id> <output-package>
#        plan-critic-package.sh --list-lenses
#   spec-file    the ticket package (title, body, comments; for an epic: the epic plus all child
#                tickets), verbatim as the tracker holds it
#   scope-file   short statement of the behavioural scope this plan was assigned, written by the
#                dispatching plan-critic agent, plus the round number if this is a re-review
#   plan-file    the planner's plan, verbatim and unedited
#   lens-id      one of: missed | misread | untestable
#
set -euo pipefail

# The single source of truth for which lenses exist; plan-critic-run.sh reads it from here rather
# than keeping its own copy, so the two cannot drift apart.
LENS_IDS="missed misread untestable"

if [ "${1:-}" = "--list-lenses" ]; then
  for lens in $LENS_IDS; do echo "$lens"; done
  exit 0
fi

if [ $# -ne 5 ]; then
  echo "usage: $0 <spec-file> <scope-file> <plan-file> <lens-id> <output-package>" >&2
  echo "       $0 --list-lenses" >&2
  exit 2
fi

SPEC="$1"
SCOPE="$2"
PLAN="$3"
LENS="$4"
OUT="$5"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for f in "$SPEC" "$SCRIPT_DIR/plan-critic-constraints.md" "$SCOPE" "$PLAN"; do
  [ -f "$f" ] || { echo "missing required file: $f" >&2; exit 2; }
done

# An unknown lens id is a hard failure, never a silently lens-less package: a critic without a
# lens would answer a different question than the two it is being compared against.
case " $LENS_IDS " in
  *" $LENS "*) ;;
  *) echo "unknown lens id: '$LENS' (expected one of: $LENS_IDS)" >&2; exit 2 ;;
esac

emit_lens() {
  case "$1" in
    missed)
      cat <<'LENS_MISSED'
This run's lens: REQUIREMENTS THE PLAN NEVER ADDRESSES.

Read the specification against the scope assigned to this plan and look for requirements that
fall inside that scope and that the plan does not address at all. Not addressed badly, not
addressed partially — absent. Something the specification demands, that nothing in the plan
would produce, and that no plan step is even aimed at.

Judge coverage, not quality. A requirement the plan does address but gets wrong is not this
run's finding, however wrong it is — report only what is missing outright. Requirements outside
the assigned scope are not findings either; if you mention one, say explicitly that it is out of
scope.
LENS_MISSED
      ;;
    misread)
      cat <<'LENS_MISREAD'
This run's lens: REQUIREMENTS THE PLAN ADDRESSES BUT MISREADS.

For each requirement the plan does address, hold what the requirement actually demands against
what the plan would actually produce, and look for the gap between them. Read too narrowly or too
broadly; a condition, qualifier or edge case dropped; a value, threshold or unit the
specification fixes and the plan quietly changes; the requirement satisfied under one
circumstance the specification states but not another; work the specification assigns to a
different system; an approach that would satisfy the words of the requirement while missing what
it is plainly for.

Judge fidelity, not coverage. A requirement the plan never mentions at all is not this run's
finding — quote the plan's own words next to the requirement's and show where they diverge.
LENS_MISREAD
      ;;
    untestable)
      cat <<'LENS_UNTESTABLE'
This run's lens: BEHAVIOUR STATED TOO VAGUELY TO DRIVE A FAILING TEST.

Every behaviour this plan claims has to be described sharply enough that a test designer could
derive from it a driving test that fails for the right reason before the production code exists.
For each behaviour the plan states, judge whether such a test could be derived at all: are the
trigger, the observable result, and the conditions under which it must hold stated precisely
enough to tell a pass from a failure? Wording that cannot come out false — "handles it
correctly", "works as expected", "properly synchronised" — is what you are looking for, along
with missing thresholds, unstated timing bounds, and results named without saying what would be
observed.

Hard limit on this lens, and it is not negotiable: do NOT enumerate concrete test cases and do
NOT propose any. A plan is required to state what will prove each behaviour, at a level a test
designer can work from — it is explicitly NOT required to list test cases, and a finding that
demands them would be a finding against a rule the plan is right to follow. You judge only
WHETHER a failing test is derivable from the plan's own words, and where it is not, name what is
missing from the description. Never which test to write.
LENS_UNTESTABLE
      ;;
  esac
}

{
  cat <<'HEADER'
You are reviewing an implementation plan against the specification it is supposed to satisfy.

This message contains everything you get: the specification in full, fixed project constraints,
the scope this plan was assigned, the plan itself, and the review lens for this run. There is no
codebase to consult and no further information available. Judge the plan on what is here.

Work through the plan step by step and dependency by dependency, judging each against a specific
requirement you quote from the specification. Record what is sound as explicitly as what is not.
Any claim the plan makes about code, assets, or behaviour that already exists is something you
cannot verify from here — record it as an unverified assumption rather than accepting it or
treating it as an error. Do not invent problems; an empty findings list is a correct result for a
good plan. Do not rewrite the plan.

================================================================================
PART 1 — SPECIFICATION: THE TICKET (verbatim, complete, authoritative)
================================================================================
HEADER
  cat "$SPEC"
  cat <<'MID1'

================================================================================
PART 2 — FIXED PROJECT CONSTRAINTS
================================================================================
MID1
  cat "$SCRIPT_DIR/plan-critic-constraints.md"
  cat <<'MID2'

================================================================================
PART 3 — SCOPE ASSIGNED TO THIS PLAN
================================================================================
MID2
  cat "$SCOPE"
  cat <<'MID3'

================================================================================
PART 4 — THE PLAN UNDER REVIEW (verbatim, unedited)
================================================================================
MID3
  cat "$PLAN"
  cat <<'MID4'

================================================================================
PART 5 — REVIEW LENS FOR THIS RUN
================================================================================

Two other reviewers are reading this same package right now under different lenses. Everything
above is identical for all three of us; only this section differs. So report findings for your
lens only and leave theirs to them — a problem you can see but that belongs to another lens will
be caught there, and duplicating it here only makes the merged report harder to act on. Your
step-by-step assessments, what you record as solid, and the claims you cannot verify are not
restricted by the lens: write those for the whole plan as usual.

MID4
  emit_lens "$LENS"
} > "$OUT"

echo "package written to $OUT ($(wc -c < "$OUT") bytes, lens: $LENS)"
