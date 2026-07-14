"""
Regression tests for ticket #74: TDD granularity relaxed from "every
individual new/extended test" to "every behavioural requirement" across
planner/developer/reviewer/AGENTS.md, while still requiring convincing,
non-fabricated red->green evidence per requirement.

This is a GRANULARITY relaxation (behaviour vs. individual test), NOT a scope
change — the "all ticket types, bug AND feature" scope invariant from ticket
#62 must be preserved verbatim and must not be conflated with this change.

Root cause: the pre-#74 prose anchored red->green to "every new or extended
test," which pushed agents toward fabricating artificial per-test failures
instead of demonstrating the missing behaviour once via a single driving
test.

Red->green: these tests fail against the pre-#74 prose (no "behavioural
requirement" / "driving test" vocabulary, no canonical evidence fields, no
Valid RED definition, no non-behavioural exemption, no retroactive/fix-
iteration rules) and pass after the #74 rework.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PLANNER_MD = REPO_ROOT / "agents" / "planner.md"
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Group 1 — planner declares the expected RED state per behavioural requirement
# ---------------------------------------------------------------------------


def test_planner_documents_canonical_evidence_fields_per_behavioural_requirement():
    text = _read(PLANNER_MD)
    assert re.search(r"behavioural requirement", text, re.IGNORECASE), (
        "agents/planner.md must document the plan per BEHAVIOURAL REQUIREMENT, "
        "not per individual test"
    )
    for field in (
        "Behaviour", "Driving test", "Expected RED reason",
        "Expected GREEN outcome", "Additional edge-case coverage",
    ):
        assert field in text, (
            f"agents/planner.md must use the canonical evidence field {field!r}"
        )


def test_planner_allows_additional_coverage_to_already_pass():
    text = _read(PLANNER_MD)
    assert re.search(r"already pass", text, re.IGNORECASE), (
        "agents/planner.md must explicitly allow additional edge-case coverage "
        "tests to already pass — only the driving test needs to fail first"
    )


# ---------------------------------------------------------------------------
# Group 2 — developer performs TDD per behavioural requirement, not per test
# ---------------------------------------------------------------------------


def test_developer_tdd_is_per_behavioural_requirement_not_per_test():
    text = _read(DEVELOPER_MD)
    assert re.search(r"per behavioural requirement", text, re.IGNORECASE), (
        "agents/developer.md must anchor TDD to 'per behavioural requirement', "
        "not per individual new/extended test"
    )
    assert re.search(r"driving test", text, re.IGNORECASE), (
        "agents/developer.md must introduce the 'driving test' concept — the "
        "one test that demonstrates the missing behaviour"
    )


def test_developer_additional_coverage_may_already_pass():
    text = _read(DEVELOPER_MD)
    assert re.search(
        r"additional coverage.{0,120}already pass|already pass.{0,120}additional coverage",
        text, re.IGNORECASE | re.DOTALL,
    ), (
        "agents/developer.md must explicitly permit additional coverage tests "
        "to already pass — they must not each need their own red run"
    )


def test_developer_over_relaxation_guard_no_residual_per_test_mandate():
    """Negative assertion: the old per-test red->green mandate phrasing must
    no longer appear as the operative requirement (granularity moved to the
    behavioural requirement / driving test)."""
    text = _read(DEVELOPER_MD)
    assert not re.search(
        r"for\s+every\s+new\s+or\s+extended\s+test|for\s+each\s+new\s+or\s+extended\s+test",
        text, re.IGNORECASE,
    ), (
        "agents/developer.md must no longer mandate red->green 'for every/each "
        "new or extended test' — that per-test granularity was relaxed to "
        "per-behavioural-requirement by ticket #74"
    )


# ---------------------------------------------------------------------------
# Group 3 — Valid RED, defined once, shared
# ---------------------------------------------------------------------------


def test_developer_defines_valid_red():
    text = _read(DEVELOPER_MD)
    assert re.search(r"valid red", text, re.IGNORECASE), (
        "agents/developer.md must define 'Valid RED'"
    )
    lower = text.lower()
    for excluded in (
        "syntax error", "import failure", "missing dependenc",
        "broken environment", "unrelated failing test", "wrong working directory",
    ):
        assert excluded in lower, (
            f"agents/developer.md's Valid RED definition must exclude {excluded!r}"
        )


# ---------------------------------------------------------------------------
# Group 4 — baseline discipline
# ---------------------------------------------------------------------------


def test_developer_baseline_discipline_documented():
    text = _read(DEVELOPER_MD)
    assert re.search(r"baseline discipline", text, re.IGNORECASE), (
        "agents/developer.md must document baseline discipline: run relevant "
        "existing tests green before the new driving test"
    )
    assert re.search(
        r"small\s+RED.{0,10}GREEN\s+loops|small\s+red.{0,10}green\s+loops",
        text, re.IGNORECASE,
    ), (
        "agents/developer.md must prefer small RED->GREEN loops per "
        "behavioural requirement over one big implement-then-test pass"
    )


# ---------------------------------------------------------------------------
# Group 5 — structured evidence format in the change report
# ---------------------------------------------------------------------------


def test_developer_change_report_structured_evidence_fields():
    text = _read(DEVELOPER_MD)
    for field in (
        "Behaviour", "Driving test", "RED", "GREEN", "Additional coverage",
        "Final suite result",
    ):
        assert field in text, (
            f"agents/developer.md's change report must use the canonical "
            f"structured-evidence field {field!r}"
        )


# ---------------------------------------------------------------------------
# Group 6 — non-behavioural exemption
# ---------------------------------------------------------------------------


def test_developer_non_behavioural_changes_exempt_from_tdd():
    text = _read(DEVELOPER_MD)
    lower = text.lower()
    for term in (
        "docs", "formatting", "comments", "dependency bump", "build config",
        "pure refactoring",
    ):
        assert term in lower, (
            f"agents/developer.md must exempt {term!r} from the TDD mandate"
        )
    assert re.search(
        r"pure refactoring.{0,200}GREEN baseline|GREEN baseline.{0,200}pure refactoring",
        text, re.IGNORECASE | re.DOTALL,
    ), (
        "agents/developer.md must require pure refactoring to preserve a "
        "GREEN baseline rather than manufacture an artificial RED"
    )


def test_reviewer_non_behavioural_changes_exempt_from_tdd():
    text = _read(REVIEWER_MD)
    assert re.search(r"non-behavioural", text, re.IGNORECASE), (
        "agents/reviewer.md must document the non-behavioural TDD exemption"
    )
    assert re.search(r"pure refactoring", text, re.IGNORECASE), (
        "agents/reviewer.md must name pure refactoring in the non-behavioural "
        "exemption"
    )


# ---------------------------------------------------------------------------
# Group 7 — retroactive tests, honestly disclosed
# ---------------------------------------------------------------------------


def test_developer_retroactive_tests_honest_disclosure():
    text = _read(DEVELOPER_MD)
    assert re.search(r"retroactive", text, re.IGNORECASE), (
        "agents/developer.md must document retroactive-test disclosure"
    )
    assert re.search(
        r"never fabricate|no fabricated|not fabricate", text, re.IGNORECASE
    ), (
        "agents/developer.md must forbid fabricating a historical RED for a "
        "retroactive test"
    )


def test_reviewer_retroactive_tests_evaluated_for_protective_value():
    text = _read(REVIEWER_MD)
    assert re.search(r"retroactive", text, re.IGNORECASE), (
        "agents/reviewer.md must document how retroactive tests are evaluated"
    )
    assert re.search(r"protective value", text, re.IGNORECASE), (
        "agents/reviewer.md must ask whether a retroactive test has protective "
        "value going forward"
    )


# ---------------------------------------------------------------------------
# Group 8 — fix iterations append, not overwrite
# ---------------------------------------------------------------------------


def test_developer_fix_iterations_append_not_overwrite():
    text = _read(DEVELOPER_MD)
    assert re.search(r"append", text, re.IGNORECASE) and re.search(
        r"not overwrite|does not overwrite|do not overwrite", text, re.IGNORECASE
    ), (
        "agents/developer.md must require fix-iteration evidence to be "
        "appended, not overwritten"
    )


def test_reviewer_fix_iterations_append_not_overwrite():
    text = _read(REVIEWER_MD)
    assert re.search(r"append", text, re.IGNORECASE), (
        "agents/reviewer.md must confirm fix-iteration evidence is appended, "
        "not overwritten, across review rounds"
    )


# ---------------------------------------------------------------------------
# Group 9 — reviewer validates behaviourally, must not require every
# additional test to have been red
# ---------------------------------------------------------------------------


def test_reviewer_validates_driving_test_red_for_expected_reason():
    text = _read(REVIEWER_MD)
    assert re.search(r"driving test", text, re.IGNORECASE), (
        "agents/reviewer.md must validate the existence of a driving test per "
        "behavioural requirement"
    )
    assert re.search(r"expected reason", text, re.IGNORECASE), (
        "agents/reviewer.md must confirm RED failed for the EXPECTED reason, "
        "not merely that it failed at all"
    )


def test_reviewer_must_not_require_every_additional_test_red():
    text = _read(REVIEWER_MD)
    assert re.search(
        r"must\s+not\s+require.{0,120}(additional coverage|every).{0,120}red|"
        r"not\s+require\s+that\s+every\s+additional",
        text, re.IGNORECASE | re.DOTALL,
    ), (
        "agents/reviewer.md must explicitly state it must NOT require every "
        "additional coverage test to have been red"
    )


# ---------------------------------------------------------------------------
# Group 10 — scope invariant (bug AND feature) is preserved, not conflated
# ---------------------------------------------------------------------------


def test_scope_invariant_bug_and_feature_preserved_in_developer_and_reviewer():
    dev = _read(DEVELOPER_MD)
    rev = _read(REVIEWER_MD)
    assert re.search(r"bug\s+AND\s+feature", dev), (
        "agents/developer.md must preserve the 'bug AND feature' scope "
        "invariant verbatim"
    )
    assert re.search(r"bug\s+and\s+feature", rev, re.IGNORECASE), (
        "agents/reviewer.md must preserve the 'bug and feature' scope "
        "invariant"
    )


def test_scope_invariant_bug_and_feature_preserved_in_planner():
    """Ticket #74 follow-up: planner.md's Test/verification strategy section
    must state the parallel feature-ticket driving-test requirement using the
    same 'bug AND feature' scope-invariant wording as developer.md/
    reviewer.md, so the concrete per-ticket-type checklist isn't bug-only."""
    text = _read(PLANNER_MD)
    assert re.search(r"bug\s+AND\s+feature", text), (
        "agents/planner.md must state the parallel feature-ticket driving "
        "test requirement (a driving test demonstrating the new behaviour, "
        "failing until it exists) using the 'bug AND feature' scope-invariant "
        "wording — otherwise the regression-test-for-bugs bullet reads as "
        "the only concrete instruction, under-specifying feature tickets"
    )


# ---------------------------------------------------------------------------
# Group 11 — AGENTS.md documents the granularity invariant, distinct from scope
# ---------------------------------------------------------------------------


def test_agents_md_documents_granularity_invariant_distinct_from_scope():
    text = _read(AGENTS_MD)
    assert re.search(r"behavioural requirement", text, re.IGNORECASE), (
        "AGENTS.md must document the per-behavioural-requirement granularity "
        "invariant"
    )
    assert re.search(r"granularity", text, re.IGNORECASE), (
        "AGENTS.md must describe this as a GRANULARITY relaxation"
    )
    assert re.search(r"distinct from|not.{0,20}conflat", text, re.IGNORECASE), (
        "AGENTS.md must explicitly distinguish the granularity relaxation "
        "from the scope invariant so the two are not conflated"
    )


def test_agents_md_updates_three_agent_chain_bullets():
    text = _read(AGENTS_MD)
    assert re.search(r"driving test", text, re.IGNORECASE), (
        "AGENTS.md's three-agent chain description must mention the driving "
        "test concept"
    )
    assert re.search(r"structured evidence", text, re.IGNORECASE), (
        "AGENTS.md must mention the developer's structured evidence report"
    )


def test_agents_md_documents_valid_red_and_non_behavioural_exemption():
    text = _read(AGENTS_MD)
    assert re.search(r"valid red", text, re.IGNORECASE), (
        "AGENTS.md must document the Valid RED definition"
    )
    assert re.search(r"non-behavioural", text, re.IGNORECASE), (
        "AGENTS.md must document the non-behavioural TDD exemption"
    )
    assert re.search(r"retroactive", text, re.IGNORECASE), (
        "AGENTS.md must document the retroactive-test rule"
    )
