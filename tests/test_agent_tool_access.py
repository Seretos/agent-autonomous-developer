"""
Regression tests for ticket #32: subagent MCP tool access.

The `developer` and `reviewer` agents were restricted to a narrow `tools:`
allowlist in their frontmatter. This prevented them from accessing MCP tools
connected in the session (e.g. Unity tools in a Unity project).

Fix: Replace the `tools:` allowlist with a `disallowedTools:` denylist.
Both agents then inherit whatever MCP tools are connected, while preserving
the safety invariants:
  - developer cannot do PR/ticket/worktree-mutation operations
  - reviewer stays strictly read-only (no Edit/Write/Serena-write tools)

Red→green anchors (fail on pre-change code, pass after):
  - test_developer_has_no_tools_allowlist
  - test_reviewer_has_no_tools_allowlist
  - test_developer_has_disallowedtools
  - test_reviewer_has_disallowedtools
  - test_developer_denylist_blocks_create_pr
  - test_developer_denylist_blocks_merge_pr
  - test_developer_denylist_blocks_worktree_create
  - test_developer_denylist_blocks_worktree_remove
  - test_developer_denylist_allows_worktree_start
  - test_reviewer_denylist_blocks_edit
  - test_reviewer_denylist_blocks_write
  - test_reviewer_denylist_blocks_serena_writes
  - test_reviewer_denylist_blocks_create_pr
  - test_agents_md_documents_denylist_mechanism
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_frontmatter(text: str) -> str:
    """Return the YAML frontmatter block (between the opening and closing ---)."""
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, "Agent .md file must have a YAML frontmatter block delimited by ---"
    return m.group(1)


def _get_frontmatter_key(frontmatter: str, key: str) -> str | None:
    """Return the value of `key:` in the frontmatter, or None if absent."""
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def _denylist_entries(frontmatter: str) -> list[str]:
    """Return the individual tool names from the disallowedTools: line."""
    value = _get_frontmatter_key(frontmatter, "disallowedTools")
    if not value:
        return []
    return [entry.strip() for entry in value.split(",") if entry.strip()]


# ---------------------------------------------------------------------------
# Group 1 — No tools: allowlist
# ---------------------------------------------------------------------------

def test_developer_has_no_tools_allowlist():
    """
    REGRESSION (#32): agents/developer.md frontmatter must NOT have a `tools:`
    key. The allowlist has been replaced by a denylist.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    value = _get_frontmatter_key(frontmatter, "tools")
    assert value is None, (
        "agents/developer.md frontmatter still has a 'tools:' key — "
        "it must be replaced with 'disallowedTools:'. "
        f"Found: tools: {value}"
    )


def test_reviewer_has_no_tools_allowlist():
    """
    REGRESSION (#32): agents/reviewer.md frontmatter must NOT have a `tools:`
    key. The allowlist has been replaced by a denylist.
    """
    text = _read(REVIEWER_MD)
    frontmatter = _extract_frontmatter(text)
    value = _get_frontmatter_key(frontmatter, "tools")
    assert value is None, (
        "agents/reviewer.md frontmatter still has a 'tools:' key — "
        "it must be replaced with 'disallowedTools:'. "
        f"Found: tools: {value}"
    )


# ---------------------------------------------------------------------------
# Group 2 — disallowedTools: key is present and non-empty
# ---------------------------------------------------------------------------

def test_developer_has_disallowedtools():
    """
    REGRESSION (#32): agents/developer.md frontmatter must have a non-empty
    `disallowedTools:` key.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert entries, (
        "agents/developer.md frontmatter must have a non-empty 'disallowedTools:' key"
    )


def test_reviewer_has_disallowedtools():
    """
    REGRESSION (#32): agents/reviewer.md frontmatter must have a non-empty
    `disallowedTools:` key.
    """
    text = _read(REVIEWER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert entries, (
        "agents/reviewer.md frontmatter must have a non-empty 'disallowedTools:' key"
    )


# ---------------------------------------------------------------------------
# Group 3 — Developer denylist: PR/ticket/worktree mutations are blocked
# ---------------------------------------------------------------------------

def test_developer_denylist_blocks_create_pr():
    """
    REGRESSION (#32): developer denylist must block create_pr — demonstrable
    proof that the PR-mutation guard survived the allowlist→denylist migration.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any("create_pr" in e for e in entries), (
        "agents/developer.md disallowedTools must contain 'create_pr'. "
        f"Current denylist: {entries}"
    )


def test_developer_denylist_blocks_merge_pr():
    """
    REGRESSION (#32): developer denylist must block merge_pr.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any("merge_pr" in e for e in entries), (
        "agents/developer.md disallowedTools must contain 'merge_pr'. "
        f"Current denylist: {entries}"
    )


def test_developer_denylist_blocks_worktree_create():
    """
    REGRESSION (#32): developer denylist must block worktree_create (or
    worktree_create-equivalent) — the developer must not create new worktrees.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any("worktree_create" in e for e in entries), (
        "agents/developer.md disallowedTools must contain 'worktree_create'. "
        f"Current denylist: {entries}"
    )


def test_developer_denylist_blocks_worktree_remove():
    """
    REGRESSION (#32): developer denylist must block worktree_remove — the
    developer must not remove worktrees.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any("worktree_remove" in e for e in entries), (
        "agents/developer.md disallowedTools must contain 'worktree_remove'. "
        f"Current denylist: {entries}"
    )


def test_developer_denylist_allows_worktree_start():
    """
    REGRESSION (#32): developer denylist must NOT block worktree_start —
    the developer needs it for the long-lived-process guardrail.
    """
    text = _read(DEVELOPER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert not any("worktree_start" in e for e in entries), (
        "agents/developer.md disallowedTools must NOT contain 'worktree_start' — "
        "the developer needs it for the long-lived-process guardrail. "
        f"Current denylist: {entries}"
    )


# ---------------------------------------------------------------------------
# Group 4 — Reviewer denylist: write tools and mutations are blocked
# ---------------------------------------------------------------------------

def test_reviewer_denylist_blocks_edit():
    """
    REGRESSION (#32): reviewer denylist must block the Edit tool — the reviewer
    is read-only and must never edit code.
    """
    text = _read(REVIEWER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any(e == "Edit" for e in entries), (
        "agents/reviewer.md disallowedTools must contain 'Edit'. "
        f"Current denylist: {entries}"
    )


def test_reviewer_denylist_blocks_write():
    """
    REGRESSION (#32): reviewer denylist must block the Write tool — the reviewer
    is read-only and must never write files.
    """
    text = _read(REVIEWER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any(e == "Write" for e in entries), (
        "agents/reviewer.md disallowedTools must contain 'Write'. "
        f"Current denylist: {entries}"
    )


def test_reviewer_denylist_blocks_serena_writes():
    """
    REGRESSION (#32): reviewer denylist must block at least one Serena write
    tool (e.g. replace_symbol_body) — the reviewer must not use Serena to
    mutate code.
    """
    text = _read(REVIEWER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any("replace_symbol_body" in e for e in entries), (
        "agents/reviewer.md disallowedTools must contain 'replace_symbol_body' "
        "(Serena write guard). "
        f"Current denylist: {entries}"
    )


def test_reviewer_denylist_blocks_create_pr():
    """
    REGRESSION (#32): reviewer denylist must block create_pr — the reviewer
    must not open PRs.
    """
    text = _read(REVIEWER_MD)
    frontmatter = _extract_frontmatter(text)
    entries = _denylist_entries(frontmatter)
    assert any("create_pr" in e for e in entries), (
        "agents/reviewer.md disallowedTools must contain 'create_pr'. "
        f"Current denylist: {entries}"
    )


# ---------------------------------------------------------------------------
# Group 5 — AGENTS.md documents the denylist mechanism
# ---------------------------------------------------------------------------

def test_agents_md_documents_denylist_mechanism():
    """
    REGRESSION (#32): AGENTS.md must document that the developer/reviewer tool
    boundaries are enforced via a disallowedTools denylist (not an allowlist).
    """
    text = _read(AGENTS_MD)
    lower = text.lower()
    has_denylist_mention = "disallowedtools" in lower or "denylist" in lower
    assert has_denylist_mention, (
        "AGENTS.md must document the disallowedTools denylist mechanism. "
        "Expected 'disallowedTools' or 'denylist' to appear in AGENTS.md."
    )
