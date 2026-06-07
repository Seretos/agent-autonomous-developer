"""
Regression tests for ticket #19: sharpen skill descriptions so the
serial / single-ticket path is explicitly in scope and the prohibition
against manual execution on `main` is clearly stated.

Red→green: these tests fail against the original SKILL.md wording and pass
after the descriptions are updated.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
PROCESS_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_description(text: str) -> str:
    """Return the value of the `description:` key from YAML front-matter.

    Handles a long single-line value, e.g.:
        description: Some long text here.
    Stops at the next key (a line that begins with a word-char followed by ':')
    or at the closing '---'.
    """
    # Match the front-matter block (between the two '---' delimiters).
    fm_match = re.search(r"^---\n(.*?\n)---", text, re.DOTALL | re.MULTILINE)
    if fm_match is None:
        raise ValueError("No YAML front-matter found")
    front_matter = fm_match.group(1)
    # Find the description key — value may continue over multiple indented lines.
    desc_match = re.search(
        r"^description:\s*(.*?)(?=\n\S|\Z)", front_matter, re.DOTALL | re.MULTILINE
    )
    if desc_match is None:
        raise ValueError("No 'description:' key found in front-matter")
    # Collapse internal newlines / leading whitespace on continuation lines.
    raw = desc_match.group(1)
    value = re.sub(r"\n[ \t]+", " ", raw).strip()
    return value


# ---------------------------------------------------------------------------
# Frontmatter structure
# ---------------------------------------------------------------------------

def test_orchestrate_has_frontmatter():
    """orchestrate-tickets SKILL.md must open with '---' (YAML front-matter)."""
    text = _read(ORCHESTRATE_MD)
    assert text.startswith("---"), (
        "skills/orchestrate-tickets/SKILL.md must start with '---' front-matter"
    )


def test_process_has_frontmatter():
    """process-ticket SKILL.md must open with '---' (YAML front-matter)."""
    text = _read(PROCESS_MD)
    assert text.startswith("---"), (
        "skills/process-ticket/SKILL.md must start with '---' front-matter"
    )


def test_orchestrate_description_key_present():
    """orchestrate-tickets front-matter must contain a 'description:' key."""
    text = _read(ORCHESTRATE_MD)
    desc = _extract_description(text)
    assert desc, "description value must be non-empty"


def test_process_description_key_present():
    """process-ticket front-matter must contain a 'description:' key."""
    text = _read(PROCESS_MD)
    desc = _extract_description(text)
    assert desc, "description value must be non-empty"


# ---------------------------------------------------------------------------
# Description length cap (reasonably concise ≤ 600 chars)
# ---------------------------------------------------------------------------

DESCRIPTION_MAX_CHARS = 600


def test_orchestrate_description_length():
    """orchestrate-tickets description must be ≤ 600 characters."""
    text = _read(ORCHESTRATE_MD)
    desc = _extract_description(text)
    assert len(desc) <= DESCRIPTION_MAX_CHARS, (
        f"orchestrate-tickets description is {len(desc)} chars, "
        f"expected ≤ {DESCRIPTION_MAX_CHARS}.\nDescription:\n{desc}"
    )


def test_process_description_length():
    """process-ticket description must be ≤ 600 characters."""
    text = _read(PROCESS_MD)
    desc = _extract_description(text)
    assert len(desc) <= DESCRIPTION_MAX_CHARS, (
        f"process-ticket description is {len(desc)} chars, "
        f"expected ≤ {DESCRIPTION_MAX_CHARS}.\nDescription:\n{desc}"
    )


# ---------------------------------------------------------------------------
# Regression: orchestrate-tickets — serial/single-ticket path is in scope
# ---------------------------------------------------------------------------

def test_orchestrate_names_serial_path():
    """
    REGRESSION (#19): orchestrate-tickets SKILL.md must explicitly name the
    serial or single-ticket case as in-scope (contain 'serial' or 'single-ticket').
    """
    text = _read(ORCHESTRATE_MD)
    lower = text.lower()
    assert "serial" in lower or "single-ticket" in lower, (
        "skills/orchestrate-tickets/SKILL.md must explicitly mention the "
        "serial / single-ticket path as in-scope (keyword: 'serial' or 'single-ticket')"
    )


def test_orchestrate_prohibits_manual_execution():
    """
    REGRESSION (#19): orchestrate-tickets SKILL.md must state that manual
    inline execution is not permitted (contain 'not permitted' or 'manually').
    """
    text = _read(ORCHESTRATE_MD)
    lower = text.lower()
    assert "not permitted" in lower or "manually" in lower, (
        "skills/orchestrate-tickets/SKILL.md must explicitly state that "
        "bypassing the skill (manual/inline execution) is not permitted"
    )


# ---------------------------------------------------------------------------
# Regression: process-ticket — safety-gate enumeration
# ---------------------------------------------------------------------------

def test_process_names_code_review():
    """
    REGRESSION (#19): process-ticket SKILL.md must name 'code review' as a
    mandatory safety gate.
    """
    text = _read(PROCESS_MD)
    assert "code review" in text.lower(), (
        "skills/process-ticket/SKILL.md must explicitly mention 'code review' "
        "as a mandatory safety gate"
    )


def test_process_names_planner_gate():
    """
    REGRESSION (#19): process-ticket SKILL.md must name the planner approval
    gate (contain 'planner').
    """
    text = _read(PROCESS_MD)
    assert "planner" in text.lower(), (
        "skills/process-ticket/SKILL.md must mention the planner approval gate"
    )


def test_process_names_force_push_or_draft_pr():
    """
    REGRESSION (#19): process-ticket SKILL.md must mention the 'no force-push'
    rule or 'draft PR' as part of the safety guarantee.
    """
    text = _read(PROCESS_MD)
    lower = text.lower()
    assert "force-push" in lower or "force push" in lower or "draft pr" in lower, (
        "skills/process-ticket/SKILL.md must mention 'force-push' or 'draft PR' "
        "as part of the enumerated safety gates"
    )


def test_process_prohibits_manual_execution():
    """
    REGRESSION (#19): process-ticket SKILL.md must state that manual execution
    on main is not permitted (contain 'not permitted' or reference 'main' near
    a prohibition).
    """
    text = _read(PROCESS_MD)
    lower = text.lower()
    assert "not permitted" in lower or "bypassing" in lower, (
        "skills/process-ticket/SKILL.md must explicitly state that bypassing "
        "the skill (manual execution on main) is not permitted"
    )


# ---------------------------------------------------------------------------
# Cross-reference integrity
# ---------------------------------------------------------------------------

def test_orchestrate_mentions_process_ticket():
    """orchestrate-tickets must still cross-reference 'process-ticket'."""
    text = _read(ORCHESTRATE_MD)
    assert "process-ticket" in text, (
        "skills/orchestrate-tickets/SKILL.md must mention 'process-ticket' "
        "(two-lane cross-reference per AGENTS.md)"
    )


def test_process_mentions_orchestrate_tickets():
    """process-ticket must still cross-reference 'orchestrate-tickets'."""
    text = _read(PROCESS_MD)
    assert "orchestrate-tickets" in text, (
        "skills/process-ticket/SKILL.md must mention 'orchestrate-tickets' "
        "(two-lane cross-reference per AGENTS.md)"
    )
