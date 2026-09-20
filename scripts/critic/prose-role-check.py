#!/usr/bin/env python3
"""Classify every hunk of a unified diff as PROSE or CODE, by role (ticket #123).

A requirement whose only executor is a model reading a prose file cannot be
driven by a test that runs it: any assertion on such a file is a string
comparison. The planner may therefore declare such a requirement `none` /
`ci-evidence` (a `Prose-executed:` line) instead of `driving-test` -- but only
while everything the diff touches for it is prose. This script is the model-free
check of that claim; the reviewer runs it against the real diff.

"Prose" is defined by role -- content a model reads -- and evaluated per hunk,
not per file extension:

  * skills/**/*.md and agents/*.md
  * AGENTS.md / CLAUDE.md at any depth
  * scripts/critic/*-constraints.md and scripts/critic/*-system-prompt.txt
  * the lens heredoc bodies (`<<'LENS_*'`) inside scripts/critic/*-package.sh,
    and only the hunks lying wholly inside such a body

Everything else is CODE (default deny): README.md, tests, hooks, every other
script, and any hunk of a package script outside a lens heredoc body -- a pure
deletion there included, since it has no new-side lines to place.

Usage: prose-role-check.py --diff <file|-> --repo-root <dir>
Output, one line per hunk:  PROSE|CODE <path>:<first>-<last> <reason>
Exit:   0 every hunk is prose, 1 at least one hunk is code, 2 usage or an
        unreadable / hunk-less diff (reason on stderr).
"""
import argparse
import pathlib
import re
import sys

PROSE_PATHS = (
    (re.compile(r"^skills/.+\.md$"), "skill file"),
    (re.compile(r"^agents/[^/]+\.md$"), "agent definition"),
    (re.compile(r"(^|/)(AGENTS|CLAUDE)\.md$"), "AGENTS.md/CLAUDE.md"),
    (re.compile(r"^scripts/critic/[\w.-]+-constraints\.md$"), "critic constraints"),
    (re.compile(r"^scripts/critic/[\w.-]+-system-prompt\.txt$"), "critic system prompt"),
)
PACKAGE_SCRIPT = re.compile(r"^scripts/critic/[\w-]+-package\.sh$")
LENS_OPENER = re.compile(r"<<-?'(LENS_\w+)'")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffError(Exception):
    pass


def parse_diff(text):
    """Yield (path, first, last, pure_deletion) for every hunk."""
    lines = text.splitlines()
    hunks = []
    i, n = 0, len(lines)
    path = None
    old_path = None
    while i < n:
        line = lines[i]
        if line.startswith("diff --git "):
            path = old_path = None
            i += 1
            continue
        if line.startswith("--- ") and path is None:
            old_path = line[4:].split("\t")[0]
            i += 1
            continue
        if line.startswith("+++ ") and path is None:
            new = line[4:].split("\t")[0]
            if new == "/dev/null":
                new = old_path or ""
            path = new
            i += 1
            continue
        if line.startswith("@@"):
            m = HUNK_HEADER.match(line)
            if not m:
                raise DiffError(f"malformed hunk header: {line!r}")
            if not path:
                raise DiffError(f"hunk without a file header: {line!r}")
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            new_left = new_count
            i += 1
            while old_left > 0 or new_left > 0:
                if i >= n:
                    raise DiffError(f"hunk {line!r} ends before its line counts are met")
                body = lines[i]
                tag = body[:1]
                if tag == "\\":
                    pass
                elif tag == "+":
                    new_left -= 1
                elif tag == "-":
                    old_left -= 1
                elif tag in (" ", ""):
                    old_left -= 1
                    new_left -= 1
                else:
                    raise DiffError(f"unexpected line inside hunk {line!r}: {body!r}")
                i += 1
            while i < n and lines[i].startswith("\\"):
                i += 1
            clean = re.sub(r"^[ab]/", "", path)
            last = new_start + new_count - 1 if new_count else new_start
            hunks.append((clean, new_start, last, new_count == 0))
            continue
        i += 1
    if not hunks:
        raise DiffError("no hunks found in the diff")
    return hunks


def lens_bodies(script_path):
    """1-based inclusive (start, end) line ranges of every `<<'LENS_*'` body."""
    lines = script_path.read_text(encoding="utf-8").splitlines()
    bodies = []
    for idx, line in enumerate(lines, 1):
        m = LENS_OPENER.search(line)
        if not m:
            continue
        delim = m.group(1)
        closer = next((j for j in range(idx + 1, len(lines) + 1)
                       if lines[j - 1].strip() == delim), None)
        if closer is not None:
            bodies.append((idx + 1, closer - 1))
    return bodies


def classify(path, first, last, deletion, repo_root, cache):
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    if ".." in norm.split("/"):
        return "CODE", "path escapes the repository (default deny)"
    for pattern, label in PROSE_PATHS:
        if pattern.search(norm):
            return "PROSE", f"{label}: content a model reads"
    if PACKAGE_SCRIPT.match(norm):
        if deletion:
            return "CODE", "pure deletion in a package script has no new-side lines to place (fails closed)"
        if norm not in cache:
            script = pathlib.Path(repo_root) / norm
            cache[norm] = lens_bodies(script) if script.is_file() else None
        bodies = cache[norm]
        if bodies is None:
            return "CODE", "package script not found under --repo-root (fails closed)"
        if any(start <= first and last <= end for start, end in bodies):
            return "PROSE", "inside a LENS_ heredoc body of the package script"
        return "CODE", "hunk lies outside every LENS_ heredoc body of the package script"
    return "CODE", "path is outside the prose role table (default deny)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diff", required=True, help="unified diff file, or - for stdin")
    ap.add_argument("--repo-root", required=True, help="repository root the diff's paths are relative to")
    args = ap.parse_args(argv)

    try:
        raw = sys.stdin.buffer.read() if args.diff == "-" else pathlib.Path(args.diff).read_bytes()
        hunks = parse_diff(raw.decode("utf-8", errors="replace"))
    except (OSError, DiffError) as exc:
        print(f"prose-role-check: {exc}", file=sys.stderr)
        return 2

    cache = {}
    any_code = False
    for path, first, last, deletion in hunks:
        verdict, reason = classify(path, first, last, deletion, args.repo_root, cache)
        any_code |= verdict == "CODE"
        print(f"{verdict} {path}:{first}-{last} {reason}")
    return 1 if any_code else 0


if __name__ == "__main__":
    sys.exit(main())
