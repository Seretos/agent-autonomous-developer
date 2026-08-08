"""
tools/check_plugin_payload.py

Ticket #81: a generic release-time gate that fails the release whenever any
file referenced via ``${CLAUDE_PLUGIN_ROOT}/...`` from an agent/skill/hook
file is absent from the staged plugin distribution.

Root cause this guards against: `.github/workflows/release.yml`'s staging
step can drop a directory (e.g. `scripts/`, `hooks/`) that an agent or hook
file references at runtime via `${CLAUDE_PLUGIN_ROOT}/...`. On a marketplace
install, that reference then resolves to nothing and the referencing
feature silently degrades (see ticket #81's root cause: the Codex
second-opinion pass in agents/reviewer.md).

This module is intentionally split into pure, independently testable
functions plus a thin CLI:

  - discover_references(repo_root)      -- scan agent/skill/hook files for
                                            ${CLAUDE_PLUGIN_ROOT}/<path> refs.
  - staged_paths_from_workflow(text)     -- parse release.yml's staging step
                                            into the set of top-level paths
                                            it ships.
  - verify_stage(repo_root, stage_root)  -- resolve discovered references
                                            against an actual staged tree.
  - main(argv)                           -- CLI entry point used by
                                            release.yml itself.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# ALLOWED_UNSHIPPED — the single documented escape hatch.
#
# A referenced ${CLAUDE_PLUGIN_ROOT}/<path> that is *legitimately* not part
# of the shipped distribution (e.g. a dev-only tool referenced only in a
# comment aimed at contributors) may be added here. This lands EMPTY: as of
# ticket #81, every referenced path is shipped. Any future entry requires an
# inline justification comment — the gate is fail-closed by default; nothing
# is silently exempted.
# ---------------------------------------------------------------------------
ALLOWED_UNSHIPPED: frozenset[str] = frozenset()

# A ${CLAUDE_PLUGIN_ROOT}/<path> reference. Stops at the first character that
# cannot appear in a bare (unquoted) relative path — quote, backtick,
# backslash, whitespace, etc. — which is exactly what lets this match cleanly
# inside both Markdown (backtick/quote delimited) and JSON (backslash-escaped
# quote delimited) source text.
_REF_PATTERN = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")


@dataclass(frozen=True)
class Reference:
    """A single ``${CLAUDE_PLUGIN_ROOT}/<path>`` reference found in source."""

    path: str  # repo-relative path under the plugin root, e.g. "scripts/codex-review.mjs"
    source_file: str  # repo-relative posix path of the file that referenced it


def _scanned_files(repo_root: Path) -> list[Path]:
    """Return every file this checker scans for ${CLAUDE_PLUGIN_ROOT} refs.

    Scope: agents/*.md, skills/**/*.md, hooks/hooks.json — the same set of
    file kinds that can legitimately embed a ${CLAUDE_PLUGIN_ROOT}/... runtime
    reference (agent bodies, skill bodies, and the hooks manifest). A missing
    directory yields no matches rather than an error (Path.glob on a
    nonexistent directory is simply empty), so this is safe to call against a
    minimal synthetic repo in tests.
    """
    files: list[Path] = []
    agents_dir = repo_root / "agents"
    if agents_dir.is_dir():
        files.extend(sorted(agents_dir.glob("*.md")))
    skills_dir = repo_root / "skills"
    if skills_dir.is_dir():
        files.extend(sorted(skills_dir.glob("**/*.md")))
    hooks_json = repo_root / "hooks" / "hooks.json"
    if hooks_json.is_file():
        files.append(hooks_json)
    return files


def discover_references(repo_root: Path) -> list[Reference]:
    """Scan agent/skill/hook source files for ${CLAUDE_PLUGIN_ROOT}/<path> refs.

    Every captured path is checked — there is no extension or path-shape
    filter (ticket #81 fix-loop, reviewer finding 2: those filters used to
    silently drop extensionless references like
    "${CLAUDE_PLUGIN_ROOT}/scripts/helper" or "${CLAUDE_PLUGIN_ROOT}/LICENSE",
    which is the same "silently narrow the discovery surface" defect class
    the rest of this gate exists to prevent). The bare
    "`${CLAUDE_PLUGIN_ROOT}` points at *this*" prose mention in
    agents/reviewer.md is excluded structurally, not by a post-filter:
    _REF_PATTERN requires a literal "/" immediately after "}", and that
    prose mention has no trailing "/" at all, so it never enters the capture
    group in the first place.

    The one normalization applied to a captured candidate is stripping
    trailing "." and "/" characters one at a time — this handles a prose
    sentence ending ("...scripts/foo.mjs." -> "scripts/foo.mjs") and a
    trailing-slash directory mention ("...scripts/" -> "scripts") without
    needing a filter. This deliberately stops (does not strip further) the
    moment the remaining candidate ends in ".." — a plain ``rstrip("./")``
    would strip a trailing ".." character-by-character too, silently turning
    a contrived "${CLAUDE_PLUGIN_ROOT}/foo/.." (parent-directory reference,
    a different path than "foo") into "foo". No such reference exists in
    this codebase today, but the normalization must not be able to change a
    path's meaning. A candidate that normalizes to the empty string (the
    bare "${CLAUDE_PLUGIN_ROOT}/" root itself) is skipped — not as an
    exemption, but as an equivalence: it resolves to the plugin root, which
    trivially exists in both the repo and the stage, so emitting a
    Reference(path="") would only corrupt reference counts without catching
    anything real.
    """
    repo_root = Path(repo_root)
    references: list[Reference] = []
    for source_path in _scanned_files(repo_root):
        text = source_path.read_text(encoding="utf-8")
        rel_source = source_path.relative_to(repo_root).as_posix()
        for match in _REF_PATTERN.finditer(text):
            candidate = match.group(1)
            while candidate.endswith(("/", ".")) and not candidate.endswith(".."):
                candidate = candidate[:-1]
            if not candidate:
                continue
            references.append(Reference(path=candidate, source_file=rel_source))
    return references


# Matches "cp -a <src>/. \"$STAGE/<dest>/\"" staging lines, e.g.:
#   cp -a scripts/. "$STAGE/scripts/"
_CP_DASH_A_PATTERN = re.compile(r'cp\s+-a\s+\S+?/\.\s+"\$STAGE/([^"/]+)/"')

# Matches a plain "cp <src> \"$STAGE/...\"" line (not "cp -a"), e.g.:
#   cp README.md "$STAGE/"
#   cp .claude-plugin/plugin.json "$STAGE/.claude-plugin/"
_CP_PLAIN_PATTERN = re.compile(r'cp\s+(?!-a\b)(\S+)\s+"\$STAGE/[^"]*"')


def staged_paths_from_workflow(workflow_text: str) -> set[str]:
    """Parse release.yml's staging step into the top-level paths it ships.

    Returns the set of top-level names (directories or files) copied into
    the staged install tree, e.g. {"skills", "agents", "scripts", "hooks",
    "README.md", ...}. Used to check whether a referenced path's top-level
    directory is shipped at all.
    """
    shipped: set[str] = set()
    for match in _CP_DASH_A_PATTERN.finditer(workflow_text):
        shipped.add(match.group(1))
    for match in _CP_PLAIN_PATTERN.finditer(workflow_text):
        src = match.group(1)
        shipped.add(src.split("/")[0])
    return shipped


# ---------------------------------------------------------------------------
# Stage verification (release-time gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    """A single payload-verification failure."""

    kind: str  # "MISSING_IN_REPO" | "NOT_STAGED" | "SOURCE_NOT_STAGED"
    path: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        base = f"{self.kind}: {self.path}"
        if self.detail:
            base += f" ({self.detail})"
        return base


def verify_stage(
    repo_root: Path,
    stage_root: Path,
    allowed_unshipped: frozenset[str] = ALLOWED_UNSHIPPED,
) -> list[Problem]:
    """Resolve every discovered ${CLAUDE_PLUGIN_ROOT} reference against a
    real staged tree and report what would be broken on a marketplace
    install.

    Two independent checks:
      1. Every discovered reference must exist in the repo (MISSING_IN_REPO
         otherwise — catches a typo'd or stale reference) and, unless its
         path is in ``allowed_unshipped``, must also exist under
         ``stage_root`` (NOT_STAGED otherwise — the ticket #81 defect class).
         When the reference resolves to a *directory* in the repo, existence
         alone is not enough (ticket #81 fix-loop round 2, Codex
         second-opinion finding): the directory's contents are walked and
         compared file-by-file against the staged copy, and every repo file
         beneath it that is absent from the stage is reported as its own
         NOT_STAGED problem, keyed by that file's own path (e.g.
         "scripts/bar.mjs", not just "scripts") — consistent with how a
         missing single file is reported. An empty repo subdirectory (git
         does not track those, so one should never really appear in a real
         checkout) contributes no files to compare and therefore can never
         cause a spurious failure.
      2. Every *scanned* source file itself must be present in the stage
         (SOURCE_NOT_STAGED otherwise) — this guards against the scan going
         vacuously green because an entire directory (e.g. agents/) was
         dropped from staging, which would silently discover zero
         references to check.
    """
    repo_root = Path(repo_root)
    stage_root = Path(stage_root)
    problems: list[Problem] = []

    for source_path in _scanned_files(repo_root):
        rel_source = source_path.relative_to(repo_root).as_posix()
        staged_source = stage_root / rel_source
        if not staged_source.is_file():
            problems.append(
                Problem(
                    kind="SOURCE_NOT_STAGED",
                    path=rel_source,
                    detail="scanned source file itself is missing from the stage",
                )
            )

    for reference in discover_references(repo_root):
        repo_target = repo_root / reference.path
        if not repo_target.exists():
            problems.append(
                Problem(
                    kind="MISSING_IN_REPO",
                    path=reference.path,
                    detail=f"referenced by {reference.source_file}",
                )
            )
            continue
        if reference.path in allowed_unshipped:
            continue
        staged_target = stage_root / reference.path
        if repo_target.is_dir():
            for repo_file in sorted(p for p in repo_target.rglob("*") if p.is_file()):
                rel = repo_file.relative_to(repo_target).as_posix()
                staged_file = staged_target / rel
                if not staged_file.is_file():
                    problems.append(
                        Problem(
                            kind="NOT_STAGED",
                            path=f"{reference.path}/{rel}",
                            detail=f"referenced by {reference.source_file}",
                        )
                    )
            continue
        if not staged_target.exists():
            problems.append(
                Problem(
                    kind="NOT_STAGED",
                    path=reference.path,
                    detail=f"referenced by {reference.source_file}",
                )
            )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify every ${CLAUDE_PLUGIN_ROOT}/<path> reference in "
            "agents/skills/hooks resolves inside the staged release payload."
        )
    )
    parser.add_argument(
        "--stage",
        required=True,
        help="Path to the staged install tree (release.yml's $STAGE dir).",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to the source repo root (default: current directory).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    stage_root = Path(args.stage).resolve()

    problems = verify_stage(repo_root, stage_root)
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        print(
            f"::error::{len(problems)} referenced plugin file(s) would break "
            "on a marketplace install — see errors above.",
            file=sys.stderr,
        )
        return 1

    reference_count = len(discover_references(repo_root))
    print(
        f"OK: {reference_count} ${{CLAUDE_PLUGIN_ROOT}} reference(s) verified "
        f"staged under {stage_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
