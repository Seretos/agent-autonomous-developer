"""
Regression tests for ticket #51: dispatcher skill (model-invocable entry point).

Root cause: both `orchestrate-tickets` and `process-ticket` were model-invocable.
When a dialog starts inside a worktree the model could pick `orchestrate-tickets`
because its description is broader — the git lane state is invisible at
skill-selection time.

Fix: remove model-invocability from both backing skills and introduce a single thin
`dispatch` skill that performs a deterministic git lane check and delegates to the
correct backing skill.

Red→green: tests in Group 1 (especially test_dispatch_does_not_have_disable_model_invocation)
and Group 3 (backing skills disabled) fail before the source changes, pass after.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

DISPATCH_MD = REPO_ROOT / "skills" / "dispatch" / "SKILL.md"
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
PROCESS_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"

DESCRIPTION_MAX_CHARS = 600  # matches cap in test_skill_descriptions.py

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_frontmatter(text: str) -> str:
    """Return the raw YAML front-matter block (between the two '---' delimiters)."""
    fm_match = re.search(r"^---\n(.*?\n)---", text, re.DOTALL | re.MULTILINE)
    if fm_match is None:
        raise ValueError("No YAML front-matter found")
    return fm_match.group(1)


def _extract_description(text: str) -> str:
    """Return the value of the `description:` key from YAML front-matter.

    Handles a long single-line value, e.g.:
        description: Some long text here.
    Stops at the next key (a line that begins with a word-char followed by ':')
    or at the closing '---'.
    """
    fm_match = re.search(r"^---\n(.*?\n)---", text, re.DOTALL | re.MULTILINE)
    if fm_match is None:
        raise ValueError("No YAML front-matter found")
    front_matter = fm_match.group(1)
    desc_match = re.search(
        r"^description:\s*(.*?)(?=\n\S|\Z)", front_matter, re.DOTALL | re.MULTILINE
    )
    if desc_match is None:
        raise ValueError("No 'description:' key found in front-matter")
    raw = desc_match.group(1)
    value = re.sub(r"\n[ \t]+", " ", raw).strip()
    return value


def _extract_body(text: str) -> str:
    """Return the skill body — everything after the closing '---' of the frontmatter."""
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    if fm_end is None:
        raise ValueError("Could not find closing '---' of frontmatter")
    return text[fm_end.end():]


# ---------------------------------------------------------------------------
# Group 1 — dispatcher exists and is model-invocable (regression anchors)
# ---------------------------------------------------------------------------


def test_dispatch_has_frontmatter():
    """dispatch SKILL.md must exist and open with '---' (YAML front-matter)."""
    text = _read(DISPATCH_MD)
    assert text.startswith("---"), (
        "skills/dispatch/SKILL.md must start with '---' front-matter"
    )


def test_dispatch_has_description():
    """dispatch front-matter must contain a non-empty 'description:' key."""
    text = _read(DISPATCH_MD)
    desc = _extract_description(text)
    assert desc, "dispatch description value must be non-empty"


def test_dispatch_description_length():
    """dispatch description must be <= 600 characters (same cap as other skills)."""
    text = _read(DISPATCH_MD)
    desc = _extract_description(text)
    assert len(desc) <= DESCRIPTION_MAX_CHARS, (
        f"dispatch description is {len(desc)} chars, "
        f"expected <= {DESCRIPTION_MAX_CHARS}.\nDescription:\n{desc}"
    )


def test_dispatch_does_not_have_disable_model_invocation():
    """
    PRIMARY REGRESSION ANCHOR (#51): dispatch/SKILL.md must NOT carry
    `disable-model-invocation: true` in its frontmatter — it must remain
    model-invocable so the model can auto-select it as the entry point.
    """
    text = _read(DISPATCH_MD)
    fm = _extract_frontmatter(text)
    assert "disable-model-invocation: true" not in fm, (
        "skills/dispatch/SKILL.md must NOT have 'disable-model-invocation: true' "
        "in its frontmatter — the dispatcher must remain model-invocable"
    )


# ---------------------------------------------------------------------------
# Group 2 — dispatcher description covers both trigger surfaces
# ---------------------------------------------------------------------------


def test_dispatch_description_covers_orchestrate_trigger():
    """
    dispatch description must cover the orchestrate/fleet trigger surface so the
    model selects it for 'orchestrate tickets', 'run all open tickets', etc.
    """
    text = _read(DISPATCH_MD)
    desc = _extract_description(text)
    lower = desc.lower()
    triggers = ["orchestrat", "fleet", "all open tickets", "ticket work"]
    assert any(t in lower for t in triggers), (
        f"dispatch description must contain at least one of {triggers} "
        f"to cover the orchestrate-tickets trigger surface.\n"
        f"Current description:\n{desc}"
    )


def test_dispatch_description_covers_process_trigger():
    """
    dispatch description must cover the process-ticket trigger surface so the
    model selects it for 'process ticket #N', 'feature branch', 'worktree', etc.
    """
    text = _read(DISPATCH_MD)
    desc = _extract_description(text)
    lower = desc.lower()
    triggers = ["process ticket", "process-ticket", "feature branch", "worktree"]
    assert any(t in lower for t in triggers), (
        f"dispatch description must contain at least one of {triggers} "
        f"to cover the process-ticket trigger surface.\n"
        f"Current description:\n{desc}"
    )


# ---------------------------------------------------------------------------
# Group 3 — dispatcher body uses deterministic git lane check and delegates
# ---------------------------------------------------------------------------


def test_dispatch_body_mentions_git_rev_parse():
    """dispatch body must instruct the model to run 'git rev-parse'."""
    text = _read(DISPATCH_MD)
    body = _extract_body(text)
    assert "git rev-parse" in body, (
        "skills/dispatch/SKILL.md body must contain 'git rev-parse' "
        "(the deterministic lane-check command)"
    )


def test_dispatch_body_mentions_git_dir():
    """dispatch body must reference '--git-dir' (main-checkout lane check)."""
    text = _read(DISPATCH_MD)
    body = _extract_body(text)
    assert "--git-dir" in body, (
        "skills/dispatch/SKILL.md body must reference '--git-dir'"
    )


def test_dispatch_body_mentions_git_common_dir():
    """dispatch body must reference '--git-common-dir' (worktree lane check)."""
    text = _read(DISPATCH_MD)
    body = _extract_body(text)
    assert "--git-common-dir" in body, (
        "skills/dispatch/SKILL.md body must reference '--git-common-dir'"
    )


def test_dispatch_body_delegates_to_orchestrate():
    """dispatch body must delegate to orchestrate-tickets for the main-checkout lane."""
    text = _read(DISPATCH_MD)
    body = _extract_body(text)
    assert "orchestrate-tickets" in body, (
        "skills/dispatch/SKILL.md body must reference 'orchestrate-tickets' "
        "as the delegation target for the main-checkout lane"
    )


def test_dispatch_body_delegates_to_process():
    """dispatch body must delegate to process-ticket for the worktree lane."""
    text = _read(DISPATCH_MD)
    body = _extract_body(text)
    assert "process-ticket" in body, (
        "skills/dispatch/SKILL.md body must reference 'process-ticket' "
        "as the delegation target for the worktree lane"
    )


# ---------------------------------------------------------------------------
# Group 4 — backing skills disabled; AGENTS.md updated
# ---------------------------------------------------------------------------


def test_orchestrate_has_disable_model_invocation():
    """
    REGRESSION ANCHOR (#51): orchestrate-tickets/SKILL.md frontmatter must contain
    'disable-model-invocation: true' so the model never auto-selects it directly.
    """
    text = _read(ORCHESTRATE_MD)
    fm = _extract_frontmatter(text)
    assert "disable-model-invocation: true" in fm, (
        "skills/orchestrate-tickets/SKILL.md frontmatter must contain "
        "'disable-model-invocation: true' — the dispatcher is now the sole "
        "model-invocable entry point"
    )


def test_process_has_disable_model_invocation():
    """
    REGRESSION ANCHOR (#51): process-ticket/SKILL.md frontmatter must contain
    'disable-model-invocation: true' so the model never auto-selects it directly.
    """
    text = _read(PROCESS_MD)
    fm = _extract_frontmatter(text)
    assert "disable-model-invocation: true" in fm, (
        "skills/process-ticket/SKILL.md frontmatter must contain "
        "'disable-model-invocation: true' — the dispatcher is now the sole "
        "model-invocable entry point"
    )


def test_agents_md_mentions_dispatcher():
    """AGENTS.md must reference the 'dispatch' skill in the lane-invariant section."""
    text = _read(AGENTS_MD)
    assert "dispatch" in text, (
        "AGENTS.md must mention 'dispatch' to document the new dispatcher-guard "
        "invariant replacing the old two-lane invariant"
    )


def test_agents_md_no_longer_calls_it_matched_pair():
    """
    REGRESSION ANCHOR (#51): AGENTS.md must NOT contain the literal string
    'matched pair' — that phrase described the old two-lane invariant where both
    backing skills were model-invocable and guarded each other. The dispatcher
    replaces that pattern.
    """
    text = _read(AGENTS_MD)
    assert "matched pair" not in text, (
        "AGENTS.md must not contain 'matched pair' — the old two-lane guard "
        "phrase has been superseded by the single dispatcher-guard invariant"
    )
