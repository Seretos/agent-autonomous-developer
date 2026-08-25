"""
Regression test for ticket #12: the `repository_dispatch` client_payload sent
to agent-marketplace must contain a `tags` field equal to
["git", "organisation", "ticket", "automation"].

Ticket #97 rebuilt the dispatch payload's construction from an unquoted
`curl -d @- <<EOF` heredoc (fragile against a multi-line changelog with
backticks/quotes/newlines) to a `jq -n '<filter>'` call. This test reads the
raw YAML, extracts that jq filter, converts its jq-specific syntax (bare
object keys, `$name`-style variable references) into valid JSON by
substituting placeholders, parses it, and asserts the expected structure —
the same regression this file always guarded, just reading a jq filter now
instead of a heredoc.
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

EXPECTED_TAGS = ["git", "organisation", "ticket", "automation"]


def _extract_jq_filter(text: str) -> str:
    """Return the jq filter object passed to `jq -n ... '<filter>'` for the
    marketplace dispatch payload."""
    dispatch_step = text.split("Dispatch to agent-marketplace", 1)[1]
    match = re.search(r"jq -n.*?'(\{.*?\}\})'", dispatch_step, re.DOTALL)
    if match is None:
        raise ValueError("Could not locate the jq filter for the dispatch payload")
    return match.group(1)


def _jq_filter_to_json(filter_text: str) -> dict:
    """Turn the jq object-construction filter into parseable JSON.

    Only handles the two jq-specific constructs this filter actually uses:
    a bare (unquoted) object key, and a `$name` variable reference used as a
    value. Both are deterministically distinguishable from real JSON syntax
    here, so a placeholder substitution is enough — no real jq evaluation.
    """
    text = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", '"PLACEHOLDER"', filter_text)
    text = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', text)
    return json.loads(text)


def _payload() -> dict:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    return _jq_filter_to_json(_extract_jq_filter(raw))


def test_tags_field_present_and_correct():
    """
    Regression test: client_payload must contain
    tags == ["git", "organisation", "ticket", "automation"].
    """
    payload = _payload()
    client_payload = payload.get("client_payload", {})
    assert "tags" in client_payload, (
        "'tags' key is missing from client_payload in .github/workflows/release.yml"
    )
    assert client_payload["tags"] == EXPECTED_TAGS, (
        f"Expected tags {EXPECTED_TAGS!r}, got {client_payload['tags']!r}"
    )


def test_tags_british_spelling():
    """'organisation' must use British spelling (not 'organization')."""
    tags = _payload()["client_payload"]["tags"]
    assert "organisation" in tags, (
        "Expected 'organisation' (British spelling) in tags, got: " + repr(tags)
    )
    assert "organization" not in tags, (
        "Found 'organization' (wrong spelling) in tags; must use 'organisation'"
    )


def test_payload_json_is_valid():
    """The jq filter must be a well-formed object with the two top-level keys."""
    payload = _payload()
    assert isinstance(payload, dict)
    assert "event_type" in payload
    assert "client_payload" in payload


def test_exactly_four_tags():
    """tags must have exactly four elements."""
    tags = _payload()["client_payload"]["tags"]
    assert len(tags) == 4, f"Expected 4 tags, got {len(tags)}: {tags!r}"


def test_changelog_field_present():
    """Ticket #97: client_payload must carry a changelog field."""
    client_payload = _payload()["client_payload"]
    assert "changelog" in client_payload
