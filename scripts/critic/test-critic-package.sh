#!/usr/bin/env bash
#
# Assembles the review package handed to the isolated test critic.
#
# Assembly is a script rather than a writing task on purpose, for the same reason as
# plan-critic-package.sh: the curator of a review package is the one role that could quietly defang
# the critique — by paraphrasing the requirement, or by leaving out the case the test code is
# weakest against. So the sources are fixed here and copied verbatim, the dispatching agent
# contributes nothing but the file paths, and the package file stays on disk for anyone who wants to
# check what the critic actually saw.
#
# WHAT IS IN THE PACKAGE, AND WHY
#
# The requirement anchor is the PLAN, verbatim — not a note the test author wrote about their own
# intent. There is no separate test-case design ("recipe") layer in this plugin: the developer
# writes the driving tests straight from the plan, so the plan is the only artefact above the test
# code, and it has already been held against the ticket by plan-critic. That makes it the nearest
# thing to an external standard available at this point in the workflow. A critic anchored to
# anything the test author produced would be checking one pipeline artefact against the next and
# would report perfect fidelity for a test that faithfully implements a toothless intent — exactly
# the case this gate exists to catch.
#
# The package is deliberately SMALL: the plan, fixed constraints, the test code. Not the ticket,
# not the production code, not the rest of the suite. The judgement asked for here is
# local — "what wrong implementation would still pass this assertion" — and burying it in project
# context makes a critic measurably worse at it. Note that verbatimness, not size, is what prevents
# defanging: every part below is copied whole, and no part is selected from.
#
# THE LENS
#
# One lens, hardcoded here, named by id — the caller may not author or choose one, for the same
# reason no agent curates the package. There is exactly one question at this point in the workflow
# ("which broken implementation still passes?"), so plan-critic's three-lens split does not apply:
# splitting a single question three ways would produce the same answer three times. The list-lenses
# interface is kept anyway so the runner stays generic if a second lens is ever justified.
#
# Nothing in this package is read out of the repository, so there is no repository-root argument.
# Every part is a file the workflow already produced.
#
# Usage: test-critic-package.sh <plan-file> <tests-file> <lens-id> <output-package>
#        test-critic-package.sh --list-lenses
#   plan-file    the planner's plan for this work package, verbatim and unedited
#   tests-file   the test code the developer wrote, verbatim: the diff or the full contents of the
#                test files, concatenated with a per-file header if there are several
#   lens-id      one of: tautology
#
set -euo pipefail

# The single source of truth for which lenses exist; test-critic-run.sh reads it from here rather
# than keeping its own copy, so the two cannot drift apart.
LENS_IDS="tautology"

if [ "${1:-}" = "--list-lenses" ]; then
  for lens in $LENS_IDS; do echo "$lens"; done
  exit 0
fi

if [ $# -ne 4 ]; then
  echo "usage: $0 <plan-file> <tests-file> <lens-id> <output-package>" >&2
  echo "       $0 --list-lenses" >&2
  exit 2
fi

PLAN="$1"
TESTCODE="$2"
LENS="$3"
OUT="$4"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for f in "$SCRIPT_DIR/test-critic-constraints.md" "$PLAN" "$TESTCODE"; do
  [ -f "$f" ] || { echo "missing required file: $f" >&2; exit 2; }
done

# An unknown lens id is a hard failure, never a silently lens-less package.
case " $LENS_IDS " in
  *" $LENS "*) ;;
  *) echo "unknown lens id: '$LENS' (expected one of: $LENS_IDS)" >&2; exit 2 ;;
esac

# Symptom-anchor precondition (ticket #108): the plan's Test/verification strategy section must
# open with one of the two anchor forms `agents/planner.md` mandates -- `Symptom (verbatim from
# ticket): "<sentence>"` or `Symptom: none:<category>`. This packager carries no ticket text at
# all (see "WHAT IS IN THE PACKAGE, AND WHY" above), so this is the one place in the whole gate
# that can catch a missing or paraphrased anchor before the isolated critic ever runs -- the
# critic itself has nothing to compare the anchor against.
heading_line="$(grep -n -m1 -iE '^#+[[:space:]]*test[[:space:]]*/[[:space:]]*verification[[:space:]]*strategy' "$PLAN" | cut -d: -f1 || true)"
anchor_line=""
if [ -n "$heading_line" ]; then
  anchor_line="$(tail -n +"$((heading_line + 1))" "$PLAN" | grep -m1 '[^[:space:]]' || true)"
fi

if ! printf '%s' "$anchor_line" | grep -Eq '^Symptom \(verbatim from ticket\): ".+"$' && \
   ! printf '%s' "$anchor_line" | grep -Eq '^Symptom: none:.+$'; then
  echo "test-critic-package.sh: the plan's Test/verification strategy section must open with a" >&2
  echo "Symptom anchor line (ticket #108) -- expected the first non-blank line after the section" >&2
  echo "heading to be either:" >&2
  echo '  Symptom (verbatim from ticket): "<copied sentence(s)>"' >&2
  echo "or:" >&2
  echo "  Symptom: none:<category>" >&2
  echo "got: ${anchor_line:-<no Test/verification strategy section found>}" >&2
  exit 2
fi

emit_lens() {
  case "$1" in
    tautology)
      cat <<'LENS_TAUTOLOGY'
This run's lens: ASSERTIONS THAT DO NOT CONSTRAIN ANYTHING.

Judge only assertions belonging to a requirement PART 1 (the plan) declares evidence kind
`driving-test` for. A requirement declared `existing-suite`, `ci-evidence`, or `none` has no
driving-test obligation, so test code touching it — if any is even present — is not this lens's
concern.

For every assertion belonging to a `driving-test` requirement, name a concrete faulty implementation that would still make
it pass, and say whether anything else in this batch would catch that implementation. An assertion
no wrong implementation can be constructed against is doing real work; an assertion satisfied by
code that does nothing toward the requirement is not, however plausible it reads.

The specific shape to hunt for is the assertion that only returns what it already knows from its
own input — checking that a string handed in comes back out, that an object is non-null right after
construction, that a collection has the count the test itself put into it. A constant-returning
implementation passes those, and so does an implementation that never ran.

A related but distinct shape (ticket #108): when PART 1's Test/verification strategy section opens
with a `Symptom (verbatim from ticket): "..."` anchor stating a runtime symptom, check — across the
whole test diff you were handed, not one assertion at a time — whether ANY assertion actually
executes the action or outcome that sentence names. If every assertion touching that requirement
only inspects prose, a literal string, a file's structure, or a JSON key, and none of them runs the
actual behaviour the symptom describes, report a `critical` finding, layer `plan`, whose title and
`what` literally contain the phrase "the acceptance criterion is exercised by no test". Three
exemptions belong with this same clause, and none of them is a finding: a `Symptom: none:<category>`
anchor never fires it (there is no runtime symptom to exercise); a requirement covering the
symptom that carries a `Substitute execution:` line never fires it either (its evidence is the
pasted command output, not a test); and a requirement covering the symptom that is declared
`ci-evidence`, naming the specific CI run/job that demonstrates it (`agents/planner.md` requires
`ci-evidence` to name one), never fires it either (its evidence is that CI run, not a test) — the
plausibility of that named run against the anchor symptom is validated at the plan-critic/review
layer, not here.

Report only this. Whether the batch covers every case of the requirement, whether the tests are
tidy, whether they follow the naming convention — none of that is this run's finding.
LENS_TAUTOLOGY
      ;;
  esac
}

{
  cat <<'HEADER'
You are reviewing test code against the requirement it is supposed to prove.

This message contains everything you get: the behavioural requirement (the plan), fixed project
constraints, the test code itself, and the review lens for this run. There is no codebase to consult, no production code to read — it does not exist yet — and
no further information available. Judge the tests on what is here.

Work through the test code assertion by assertion, judging each against a specific requirement you
quote. Record what is solid as explicitly as what is not. Any claim the test code makes about types,
APIs, assets or behaviour that already exists is something you cannot verify from here — record it
as an unverified assumption rather than accepting it or treating it as an error. Do not invent
problems; an empty findings list is a correct result for a well-written test batch. Do not rewrite
the tests and do not propose additional cases.

================================================================================
PART 1 — THE BEHAVIOURAL REQUIREMENT (the plan, verbatim, unedited)
================================================================================
HEADER
  cat "$PLAN"
  cat <<'MID1'

================================================================================
PART 2 — FIXED PROJECT CONSTRAINTS
================================================================================
MID1
  cat "$SCRIPT_DIR/test-critic-constraints.md"
  cat <<'MID2'

================================================================================
PART 3 — THE TEST CODE UNDER REVIEW (verbatim, unedited)
================================================================================
MID2
  cat "$TESTCODE"
  cat <<'MID3'

================================================================================
PART 4 — REVIEW LENS FOR THIS RUN
================================================================================

MID3
  emit_lens "$LENS"
} > "$OUT"

echo "package written to $OUT ($(wc -c < "$OUT") bytes, lens: $LENS)"
