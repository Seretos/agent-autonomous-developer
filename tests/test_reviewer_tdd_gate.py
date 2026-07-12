"""
Regression tests for ticket #62: reviewer's test-coverage hard gate is
tightened to also require documented red->green evidence, in lockstep with
the developer's generalized TDD mandate (all ticket types, not just
bug/defect).

Root cause: the pre-rework agents/reviewer.md test-coverage gate checked for
a regression test and edge-case coverage, but did not require the change
report to show the red->green transition itself — a developer could report
only a final green run and still pass review.

Red→green: these tests fail against the pre-rework agents/reviewer.md (no
red->green evidence requirement) and pass after the rework.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_gate_requires_red_green_evidence_in_change_report():
    text = _read(REVIEWER_MD)
    assert re.search(r"red.{0,10}(-|→|to)\s*green|red.{0,20}green\s+transition",
                      text, re.IGNORECASE), (
        "agents/reviewer.md must extend the test-coverage gate to require "
        "red->green evidence in the change report"
    )


def test_missing_red_green_evidence_is_blocking_changes_requested():
    text = _read(REVIEWER_MD)
    assert re.search(
        r"no\s+evidence.{0,200}CHANGES_REQUESTED|CHANGES_REQUESTED.{0,200}no\s+evidence",
        text, re.DOTALL | re.IGNORECASE,
    ), (
        "agents/reviewer.md must document that missing red->green evidence "
        "produces VERDICT: CHANGES_REQUESTED"
    )
    assert "[blocking]" in text, (
        "agents/reviewer.md must tag the missing red->green evidence finding "
        "as [blocking]"
    )


def test_gate_scoped_to_test_coverage_hard_gate_section():
    """The new requirement must live inside the existing hard-gate section."""
    text = _read(REVIEWER_MD)
    m = re.search(r"Test coverage \(hard gate\)\.(.*?)(?=\n\s*-\s+\*\*|\Z)", text, re.DOTALL)
    assert m, "agents/reviewer.md must retain the 'Test coverage (hard gate)' section"
    section = m.group(0)
    assert re.search(r"red", section, re.IGNORECASE), (
        "The red->green evidence requirement must be documented inside the "
        "'Test coverage (hard gate)' section, not elsewhere"
    )
