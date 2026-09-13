"""
tools/prev_release_tag.py

Ticket #107: `.github/workflows/release.yml` tags each release at a
parent-less orphan commit, so `gh release create --generate-notes` has no
history to walk and produces an empty release body (and, since #97, an empty
marketplace PR `## Changelog`). The fix generates notes from `main`'s real
history between two lightweight `src/<TAG>` markers instead -- which requires
knowing the *previous* release's tag.

This module resolves that previous tag: strict-semver ordering, scoped to
`<plugin_name>--v*` tags, excluding the tag currently being created and any
`src/*` marker tag. It matches the one helper convention `release.yml`
already uses (`python3 tools/check_plugin_payload.py --stage ...`) rather
than opening a new `.github/scripts/*.sh` convention for a single caller.

  - previous_release_tag(candidate_tags, *, plugin_name, exclude_tag)
        -- pure resolution function.
  - VERSION_RE -- compiled strict-semver acceptance pattern (no build
        metadata, no leading zeros); the grammar authority release.yml's own
        validate-step regex is checked against
        (test_workflow_version_regex_matches_module_parser_grammar).
  - main(argv) -- CLI: reads candidate tags on stdin (one per line), prints
        the resolved tag (or nothing) to stdout, always exits 0.
"""

from __future__ import annotations

import argparse
import re
import sys

# ---------------------------------------------------------------------------
# Grammar: strict semver, no build metadata, no leading zeros.
#
# Written to be valid POSIX ERE *and* valid Python `re` (no `\d`, no `(?:`
# non-capturing groups -- bash's `[[ =~ ]]` extended-regex engine supports
# neither) so release.yml's validate-step regex can be the byte-for-byte
# bash translation of this same pattern. Deliberately omits a buildmetadata
# group entirely (rather than forbidding it via a negative construct): a
# trailing "+..." simply has nothing left to match after the optional
# prerelease group, so the overall match fails closed.
# ---------------------------------------------------------------------------
_NUMERIC_IDENT = r"(0|[1-9][0-9]*)"
_PRERELEASE_IDENT = r"(0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)"
VERSION_PATTERN = (
    rf"^{_NUMERIC_IDENT}\.{_NUMERIC_IDENT}\.{_NUMERIC_IDENT}"
    rf"(-{_PRERELEASE_IDENT}(\.{_PRERELEASE_IDENT})*)?$"
)
VERSION_RE = re.compile(VERSION_PATTERN)


def _identifier_sort_key(identifier: str) -> tuple[int, object]:
    """Per semver precedence: numeric identifiers compare numerically and
    always sort below alphanumeric ones, which compare lexically (ASCII)."""
    if identifier.isdigit():
        return (0, int(identifier))
    return (1, identifier)


def _semver_sort_key(version: str) -> tuple:
    """A tuple such that Python's default ordering reproduces semver
    precedence: numeric core compared first; a version with a prerelease
    always sorts below the same core version without one; two prereleases of
    the same core compare identifier-by-identifier (numeric before
    alphanumeric, then value), with a longer identifier list outranking a
    shared-prefix shorter one -- exactly as tuple comparison already does."""
    core, _, prerelease = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    if prerelease:
        idents = tuple(_identifier_sort_key(p) for p in prerelease.split("."))
        return (major, minor, patch, 0, idents)
    return (major, minor, patch, 1, ())


def previous_release_tag(
    candidate_tags: list[str], *, plugin_name: str, exclude_tag: str
) -> str | None:
    """Resolve the previous `<plugin_name>--v<version>` release tag by
    strict-semver precedence.

    Excludes: the tag being created (`exclude_tag`), any `src/*` marker tag,
    any tag not belonging to `plugin_name`, and any malformed (non-strict-
    semver) version suffix. Returns None when nothing remains -- the
    genuinely-first-release case, not an error.
    """
    prefix = f"{plugin_name}--v"
    best_tag: str | None = None
    best_key: tuple | None = None
    for tag in candidate_tags:
        if tag == exclude_tag:
            continue
        if tag.startswith("src/"):
            continue
        if not tag.startswith(prefix):
            continue
        version = tag[len(prefix):]
        if not VERSION_RE.match(version):
            continue
        key = _semver_sort_key(version)
        if best_key is None or key > best_key:
            best_key = key
            best_tag = tag
    return best_tag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve the previous <plugin_name>--v<version> release tag by "
            "strict-semver precedence, reading candidate tags on stdin (one "
            "per line)."
        )
    )
    parser.add_argument("--plugin-name", required=True)
    parser.add_argument("--exclude-tag", required=True)
    args = parser.parse_args(argv)

    candidates = [line.strip() for line in sys.stdin if line.strip()]
    result = previous_release_tag(
        candidates, plugin_name=args.plugin_name, exclude_tag=args.exclude_tag
    )
    if result:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
