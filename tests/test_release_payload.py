"""
Regression test for ticket #12: the `repository_dispatch` client_payload sent
to agent-marketplace must contain a `tags` field equal to
["git", "organisation", "ticket", "python"].

The test reads the raw YAML, extracts the heredoc JSON block that is passed to
`curl -d @- <<EOF`, substitutes placeholder values for every shell variable so
the block becomes valid JSON, parses it, and asserts the expected structure.
"""

import json
import pathlib
import re

WORKFLOW_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "release.yml"
)

EXPECTED_TAGS = ["git", "organisation", "ticket", "python"]


def _extract_heredoc_json(text: str) -> str:
    """Return the text between the ``<<EOF`` marker and the closing ``EOF``.

    In the YAML file the heredoc is indented, so the closing token looks like
    ``          EOF`` (leading spaces).  The regex strips leading whitespace
    from each content line so the block is parseable as plain JSON.
    """
    # Capture everything from after <<EOF up to a line that is just (optional
    # whitespace +) EOF.
    match = re.search(r"<<EOF\s*\n(.*?)\n[ \t]*EOF", text, re.DOTALL)
    if match is None:
        raise ValueError("Could not locate <<EOF ... EOF block in release.yml")
    raw_block = match.group(1)
    # Strip the common leading indentation so the JSON parses cleanly.
    lines = raw_block.splitlines()
    # Find minimum indentation of non-empty lines.
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    strip = min(indents) if indents else 0
    dedented = "\n".join(line[strip:] if len(line) >= strip else line for line in lines)
    return dedented


def _substitute_shell_vars(text: str) -> str:
    """
    Replace every shell variable reference with a safe placeholder string so
    that the block becomes parseable JSON.  We handle:
      - ${VAR}
      - ${{ github.repository }} / ${{ inputs.version }} / ${{ steps.*.outputs.* }}
    """
    # GitHub Actions expressions: ${{ ... }}
    text = re.sub(r"\$\{\{[^}]*\}\}", "PLACEHOLDER", text)
    # Regular shell variables: ${VAR} or $VAR
    text = re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", "PLACEHOLDER", text)
    text = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]+", "PLACEHOLDER", text)
    return text


def test_tags_field_present_and_correct():
    """
    Regression test: client_payload must contain
    tags == ["git", "organisation", "ticket", "python"].
    """
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    heredoc = _extract_heredoc_json(raw)
    substituted = _substitute_shell_vars(heredoc)

    try:
        payload = json.loads(substituted)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"client_payload heredoc is not valid JSON after variable substitution.\n"
            f"Substituted text:\n{substituted}\nError: {exc}"
        ) from exc

    client_payload = payload.get("client_payload", {})
    assert "tags" in client_payload, (
        "'tags' key is missing from client_payload in .github/workflows/release.yml"
    )
    assert client_payload["tags"] == EXPECTED_TAGS, (
        f"Expected tags {EXPECTED_TAGS!r}, got {client_payload['tags']!r}"
    )


def test_tags_british_spelling():
    """'organisation' must use British spelling (not 'organization')."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    heredoc = _extract_heredoc_json(raw)
    substituted = _substitute_shell_vars(heredoc)
    payload = json.loads(substituted)
    tags = payload["client_payload"]["tags"]
    assert "organisation" in tags, (
        "Expected 'organisation' (British spelling) in tags, got: " + repr(tags)
    )
    assert "organization" not in tags, (
        "Found 'organization' (wrong spelling) in tags; must use 'organisation'"
    )


def test_payload_json_is_valid():
    """The heredoc block must parse as valid JSON (no trailing/misplaced commas)."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    heredoc = _extract_heredoc_json(raw)
    substituted = _substitute_shell_vars(heredoc)
    # json.loads raises if invalid; the assertion is implicit in the absence of an exception
    payload = json.loads(substituted)
    assert isinstance(payload, dict)
    assert "event_type" in payload
    assert "client_payload" in payload


def test_exactly_four_tags():
    """tags must have exactly four elements."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    heredoc = _extract_heredoc_json(raw)
    substituted = _substitute_shell_vars(heredoc)
    payload = json.loads(substituted)
    tags = payload["client_payload"]["tags"]
    assert len(tags) == 4, f"Expected 4 tags, got {len(tags)}: {tags!r}"
