"""
Regression tests for ticket #31: Codex readiness false-negative.

When the Codex broker is cold (not pre-started), `codex-companion.mjs setup
--json` returns `ready: false` even though the user is fully authenticated
(disk credentials in ~/.codex/auth.json). The old gate (`ready: true` only)
silently skipped the Codex review — a false negative.

The fix changes the gate in agents/reviewer.md from a binary `ready: true`
check to a four-case decision tree based on `codex.available`, `ready`/
`auth.loggedIn`, and `auth.requiresOpenaiAuth`. AGENTS.md's "Presence-driven"
bullet is updated to match.

Red→green anchors:
  - test_step2_gates_on_codex_available_not_ready  (fails before edits)
  - test_step2_skips_on_genuine_no_credentials     (fails before edits)
  - test_step2_proceeds_on_cold_broker             (fails before edits)
  - test_agents_md_availability_based_gate         (fails before edits)
  - test_step2_does_not_match_on_enoent            (passes before and after)
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_codex_section(text: str) -> str:
    """Return the text of the 'Optional — Codex second opinion' section."""
    m = re.search(
        r"## Optional.*?Codex second opinion.*?(?=\n## |\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    assert m, (
        "agents/reviewer.md must contain an 'Optional — Codex second opinion' section"
    )
    return m.group(0)


def _extract_step2_block(text: str) -> str:
    """Return the text of step 2 (readiness/availability block) in the Codex section.

    Matches from the '2.' marker up to (but not including) '3.' or end of section.
    """
    section = _extract_codex_section(text)
    m = re.search(r"2\.(.*?)(?=\n\d+\.|\Z)", section, re.DOTALL)
    assert m, (
        "The Codex section in agents/reviewer.md must contain a numbered step 2"
    )
    return m.group(1)


def _extract_presence_bullet(text: str) -> str:
    """Return the 'Presence-driven, no flag' bullet from AGENTS.md."""
    m = re.search(
        r"- \*\*Presence-driven, no flag\.\*\*(.*?)(?=\n- \*\*|\Z)",
        text,
        re.DOTALL,
    )
    assert m, (
        "AGENTS.md must contain a '- **Presence-driven, no flag.**' bullet "
        "in the 'Optional Codex review augmentation' section"
    )
    return m.group(0)


# ---------------------------------------------------------------------------
# Test 1 — primary regression anchor
# The step-2 block must gate on codex.available, not only on ready: true.
# ---------------------------------------------------------------------------

def test_step2_gates_on_codex_available_not_ready():
    """
    REGRESSION (#31): step 2 of the Codex section in agents/reviewer.md must
    reference 'codex.available' as the availability gate (CLI/runtime installed),
    not gate solely on the binary 'ready' flag.
    """
    text = _read(REVIEWER_MD)
    step2 = _extract_step2_block(text)
    assert "codex.available" in step2, (
        "Step 2 of the Codex section must reference 'codex.available' as the "
        "availability gate. Current step 2 text:\n" + step2
    )


# ---------------------------------------------------------------------------
# Test 2 — genuine no-credentials case must still skip
# ---------------------------------------------------------------------------

def test_step2_skips_on_genuine_no_credentials():
    """
    REGRESSION (#31): step 2 must tie a skip to the genuine no-credentials case,
    i.e. it must reference 'requiresOpenaiAuth' alongside a skip instruction.
    """
    text = _read(REVIEWER_MD)
    step2 = _extract_step2_block(text)
    assert "requiresOpenaiAuth" in step2, (
        "Step 2 must reference 'requiresOpenaiAuth' to distinguish genuine "
        "no-credentials from a cold-broker state. Current step 2 text:\n" + step2
    )
    # The block must also instruct to skip in that case.
    lower = step2.lower()
    assert "skip" in lower, (
        "Step 2 must instruct to skip when genuinely not authenticated. "
        "Current step 2 text:\n" + step2
    )


# ---------------------------------------------------------------------------
# Test 3 — cold broker must lead to proceeding, not skipping
# ---------------------------------------------------------------------------

def test_step2_proceeds_on_cold_broker():
    """
    REGRESSION (#31): step 2 must indicate that a cold/transient broker state
    (loggedIn false but requiresOpenaiAuth not true) leads to proceeding with
    the review, not skipping unconditionally.

    The old text only says 'proceed' for the authenticated case and skips
    otherwise. The new text must explicitly indicate that the cold-broker
    case (requiresOpenaiAuth null/absent/false) leads to proceeding.
    We anchor on both 'requiresOpenaiAuth' (the distinguishing field) and
    'proceed' appearing together — or on the explicit 'cold' / 'on-demand'
    phrasing the plan requires.
    """
    text = _read(REVIEWER_MD)
    step2 = _extract_step2_block(text)
    lower = step2.lower()
    # The plan requires the cold-broker case to be explicitly described.
    # The new text must reference at least one of: 'cold', 'on-demand',
    # 'transient', or the combination of requiresOpenaiAuth + proceed.
    has_cold_broker_phrasing = (
        "cold" in lower
        or "on-demand" in lower
        or "on demand" in lower
        or "transient" in lower
    )
    has_field_plus_proceed = "requiresOpenaiAuth" in step2 and "proceed" in lower
    assert has_cold_broker_phrasing or has_field_plus_proceed, (
        "Step 2 must explicitly describe the cold-broker path (e.g. mention "
        "'cold', 'on-demand', 'transient', or pair requiresOpenaiAuth with "
        "'proceed'). Current step 2 text:\n" + step2
    )


# ---------------------------------------------------------------------------
# Test 4 — ENOENT / named-pipe string-matching must NOT appear
# (passes before edits and must keep passing after)
# ---------------------------------------------------------------------------

def test_step2_does_not_match_on_enoent():
    """
    Guard: step 2 must NOT prescribe checking 'ENOENT' or named-pipe/socket
    error strings as a detection mechanism. The only permitted occurrence of
    'ENOENT' in step 2 is inside a prohibition instruction (e.g. 'Do NOT use
    ENOENT'). This guards against reintroducing the fragile approach.
    """
    text = _read(REVIEWER_MD)
    step2 = _extract_step2_block(text)

    # If ENOENT appears, it must only appear as part of a prohibition, not as
    # something the agent is instructed to detect/match. Look for patterns like
    # 'catch ENOENT', 'if ENOENT', 'match ENOENT', 'on ENOENT' etc.
    # Simple heuristic: any line with ENOENT must also contain a negation word
    # (NOT, never, do not, don't) — i.e. it is documenting a prohibition.
    for line in step2.splitlines():
        if "ENOENT" in line:
            line_lower = line.lower()
            has_negation = any(
                kw in line_lower
                for kw in ("not ", "never", "do not", "don’t")
            )
            assert has_negation, (
                "Step 2 contains 'ENOENT' outside of a prohibition context — "
                "this would reintroduce fragile string-matching. "
                "Line: " + line.strip() + "\nFull step 2:\n" + step2
            )

    # Named-pipe / socket matching: same negation heuristic.
    # Any line containing these terms must also carry a negation word
    # (i.e. documenting why they must NOT be used, not instructing their use).
    for kw in ("named-pipe", "named pipe"):
        for line in step2.splitlines():
            if kw in line.lower():
                line_lower = line.lower()
                has_negation = any(
                    neg in line_lower
                    for neg in ("not ", "never", "do not", "don’t")
                )
                assert has_negation, (
                    f"Step 2 references '{kw}' outside a prohibition context — "
                    "this would reintroduce fragile string-matching. "
                    "Line: " + line.strip() + "\nFull step 2:\n" + step2
                )


# ---------------------------------------------------------------------------
# Test 5 — AGENTS.md 'Presence-driven' bullet must describe availability gate
# ---------------------------------------------------------------------------

def test_agents_md_availability_based_gate():
    """
    REGRESSION (#31): AGENTS.md's 'Presence-driven, no flag' bullet must
    describe the availability-based gate (reference 'codex.available' or
    'availability') rather than only 'ready: true'.

    Additionally, a cold broker (loggedIn false, requiresOpenaiAuth not true)
    must NOT be described as 'not authenticated' — the bullet must NOT combine
    'ready: true' as the sole gate without the availability nuance.
    """
    text = _read(AGENTS_MD)
    bullet = _extract_presence_bullet(text)
    lower = bullet.lower()

    # Must reference the availability field or concept.
    has_availability = "codex.available" in bullet or "availability" in lower
    assert has_availability, (
        "AGENTS.md 'Presence-driven' bullet must reference 'codex.available' "
        "or 'availability' to describe the new gate. Current bullet:\n" + bullet
    )

    # Must NOT still say 'ready: true' as the sole gate (the old incorrect gate).
    # It's acceptable to mention 'ready' in context, but not as 'gate on ready: true'.
    assert "gate on `codex-companion.mjs setup --json` returning `ready: true`" not in bullet, (
        "AGENTS.md 'Presence-driven' bullet still contains the old gate description "
        "('gate on ... returning `ready: true`'). Update it to the availability-based "
        "gate. Current bullet:\n" + bullet
    )
