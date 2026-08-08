"""
Regression tests for ticket #49: Codex review silently skipped on Windows.

The root cause was that adversarial-review --wait produces an empty diff in the
App-Server sandbox on Windows with unstaged working-tree changes, causing the
reviewer to fall through to "Codex unavailable" and issue APPROVE with no Codex
findings.

The fix ships a bundled script (scripts/codex-review.mjs) that uses
git add -A + git diff --staged to collect the diff robustly before feeding it
to Codex via task --prompt-file — platform-agnostic and works on Windows.

Red->green anchors (fail before the fix, pass after):
  - test_script_exists                    (script file must be created)
  - test_script_has_working_tree_mode     (mode must be implemented)
  - test_script_uses_staged_diff          (Windows-safe diff collection)
  - test_script_exits_zero_on_empty_diff  (soft-fail, not hard error)
  - test_script_no_write_flag             (Codex stays read-only)
  - test_reviewer_uses_bundled_script     (reviewer.md wired to new script)
  - test_reviewer_no_diff_size_branch     (old size-branch logic removed)
  - test_reviewer_soft_fail_is_visible    (soft-fail never silently APPROVE)
  - test_agents_md_updated_description    (AGENTS.md reflects new approach)
"""

import pathlib
import re
import shutil
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

SCRIPT_PATH = REPO_ROOT / "scripts" / "codex-review.mjs"
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


# ---------------------------------------------------------------------------
# Test 1 — script must exist
# ---------------------------------------------------------------------------

def test_script_exists():
    """
    REGRESSION (#49): scripts/codex-review.mjs must exist.
    Before the fix, no bundled review script existed.
    """
    assert SCRIPT_PATH.exists(), (
        f"scripts/codex-review.mjs does not exist at {SCRIPT_PATH}. "
        "The bundled review script must be created."
    )


# ---------------------------------------------------------------------------
# Test 2 — script must implement working-tree mode
# ---------------------------------------------------------------------------

def test_script_has_working_tree_mode():
    """
    REGRESSION (#49): the bundled script must implement 'working-tree' mode
    and contain 'git add -A' (staging all changes before diff collection).
    """
    src = _read(SCRIPT_PATH)
    assert "working-tree" in src, (
        "scripts/codex-review.mjs must contain the 'working-tree' mode string."
    )
    assert "git add -A" in src or '"add", "-A"' in src or '"-A"' in src, (
        "scripts/codex-review.mjs must stage all changes via git add -A before "
        "collecting the diff (the Windows-safe path)."
    )


# ---------------------------------------------------------------------------
# Test 3 — script must use staged diff, not a branch-range diff
# ---------------------------------------------------------------------------

def test_script_uses_staged_diff():
    """
    REGRESSION (#49): the working-tree mode must use 'git diff --staged' to
    collect the diff, NOT 'git diff origin/<branch>...HEAD' (which produces an
    empty result in the App-Server sandbox on Windows).
    """
    src = _read(SCRIPT_PATH)
    # Must contain --staged (the Windows-safe path).
    assert "--staged" in src, (
        "scripts/codex-review.mjs must use 'git diff --staged' to collect the "
        "diff. This is the platform-agnostic, Windows-safe approach."
    )
    # Must NOT use the branch-range path as the primary working-tree diff.
    # We check for the typical branch-range pattern; 'adversarial-review' in
    # the branch mode block is fine, but using origin/...HEAD for the
    # working-tree diff is the root-cause bug.
    branch_range_pattern = re.compile(r"git[\"'\s]+diff[\"'\s]+origin/.*?\.\.\.HEAD")
    matches = branch_range_pattern.findall(src)
    # Allow it only inside a comment or the branch-mode function, not as a
    # direct git diff call for the working-tree collection.
    for m in matches:
        # If the pattern appears, it must be inside the branch mode section.
        # We locate where this match appears in the source and check context.
        idx = src.find(m)
        surrounding = src[max(0, idx - 200):idx + 200]
        assert "branch" in surrounding.lower() or "adversarial" in surrounding.lower(), (
            f"Found 'git diff origin/...HEAD' pattern outside branch mode context: {m!r}. "
            "The working-tree mode must use 'git diff --staged' instead."
        )


# ---------------------------------------------------------------------------
# Test 4 — script must soft-fail on empty diff
# ---------------------------------------------------------------------------

def test_script_exits_zero_on_empty_diff():
    """
    REGRESSION (#49): when the staged diff is empty the script must emit a
    'Codex review unavailable: ...' line (no VERDICT) and exit 0 — never raise
    a hard error that could block the reviewer.
    """
    src = _read(SCRIPT_PATH)
    # The script must contain the empty-diff soft-fail logic.
    has_empty_check = (
        "empty working-tree diff" in src
        or ("empty" in src and "softFail" in src)
        or ("trim()" in src and "softFail" in src)
    )
    assert has_empty_check, (
        "scripts/codex-review.mjs must handle an empty staged diff as a soft-fail "
        "(emit 'Codex review unavailable: ...' with no VERDICT line, exit 0)."
    )
    # The 'Codex review unavailable' prefix must be present for soft-fail output.
    assert "Codex review unavailable" in src, (
        "scripts/codex-review.mjs must emit 'Codex review unavailable: <reason>' "
        "on any soft-fail path (empty diff, companion error, etc.)."
    )
    # The script must always exit 0 — look for process.exit(0) in error paths.
    assert "process.exit(0)" in src, (
        "scripts/codex-review.mjs must call process.exit(0) — it must never "
        "block the reviewer pipeline with a non-zero exit."
    )


# ---------------------------------------------------------------------------
# Test 5 — --write must never appear in the script
# ---------------------------------------------------------------------------

def test_script_no_write_flag():
    """
    REGRESSION (#49): '--write' must not be passed as an argument to Codex in
    scripts/codex-review.mjs. Codex must remain read-only.

    Note: '--write' may appear in doc-comment lines that explain the constraint
    (e.g. "Never pass --write"). The test only fails if '--write' appears as a
    code argument (inside a string literal in a non-comment line).
    """
    src = _read(SCRIPT_PATH)
    # Filter to non-comment lines and check those do not contain '--write'
    # as an array element or string argument being passed to node.
    # A comment line starts with optional whitespace followed by * or //.
    import re as _re
    comment_line = _re.compile(r"^\s*(?:\*|//)")
    for line in src.splitlines():
        if comment_line.match(line):
            continue  # skip doc/line comment lines
        # In code lines, '--write' must not appear as a passed argument.
        # We look for it as a quoted string (the form used in spawnSync args).
        if '"--write"' in line or "'--write'" in line:
            raise AssertionError(
                f"scripts/codex-review.mjs passes '--write' to Codex as an "
                f"argument. The script is review-only and must never pass "
                f"--write. Line: {line.strip()!r}"
            )


# ---------------------------------------------------------------------------
# Test 6 — reviewer.md must reference the bundled script
# ---------------------------------------------------------------------------

def test_reviewer_uses_bundled_script():
    """
    REGRESSION (#49): agents/reviewer.md must reference
    'scripts/codex-review.mjs' and 'working-tree' in the Codex section,
    wiring the reviewer to the new bundled script.
    """
    text = _read(REVIEWER_MD)
    section = _extract_codex_section(text)
    assert "scripts/codex-review.mjs" in section, (
        "agents/reviewer.md Codex section must reference 'scripts/codex-review.mjs'."
    )
    assert "working-tree" in section, (
        "agents/reviewer.md Codex section must reference 'working-tree' mode."
    )


# ---------------------------------------------------------------------------
# Test 7 — reviewer.md must not contain the old diff-size branch logic
# ---------------------------------------------------------------------------

def test_reviewer_no_diff_size_branch():
    """
    REGRESSION (#49): the old diff-size branching logic (wc -c, Measure-Object,
    the adversarial-review size-fallback) must be removed from reviewer.md.
    These markers indicate the old two-path size-branch approach that failed
    on Windows.
    """
    text = _read(REVIEWER_MD)
    section = _extract_codex_section(text)

    # wc -c was used to measure diff size for the branch decision.
    assert "wc -c" not in section, (
        "agents/reviewer.md Codex section still contains 'wc -c' (old diff-size "
        "measurement). The size-branch logic must be removed."
    )
    # Measure-Object was the PowerShell equivalent.
    assert "Measure-Object" not in section, (
        "agents/reviewer.md Codex section still contains 'Measure-Object' (old "
        "PowerShell diff-size measurement). The size-branch logic must be removed."
    )
    # The size-fallback step labels (3a/3b/3c or similar with size context).
    # We look specifically for "3a" or "3b" combined with a size/KB reference
    # that indicates the old branch structure, not just any numbered sub-items.
    size_branch_pattern = re.compile(
        r"3[abc]\b.*?(diff|KB|180|size|measure|wc)",
        re.IGNORECASE | re.DOTALL,
    )
    m = size_branch_pattern.search(section)
    assert not m, (
        "agents/reviewer.md Codex section still contains old size-branch step "
        f"markers (3a/3b/3c with size context). Found: {m.group(0)!r}. "
        "Replace with the single bundled-script invocation."
    )


# ---------------------------------------------------------------------------
# Test 8 — soft-fail must be visible (never silently APPROVE)
# ---------------------------------------------------------------------------

def test_reviewer_soft_fail_is_visible():
    """
    REGRESSION (#49): when the bundled script soft-fails (no VERDICT line in
    output), reviewer.md must instruct the reviewer to add a visible finding —
    never silently approve. The key indicator is that a missing VERDICT triggers
    a visible finding at some severity level.
    """
    text = _read(REVIEWER_MD)
    section = _extract_codex_section(text)
    lower = section.lower()

    # The section must describe what to do when there's NO VERDICT line.
    no_verdict_indicator = (
        "no verdict" in lower
        or "no `verdict`" in lower
        or "contains no verdict" in lower
        or "does not contain a verdict" in lower
        or "missing verdict" in lower
        or ("verdict" in lower and "no" in lower and "line" in lower)
        # Cover the phrasing: "If the output contains NO VERDICT: line"
        or re.search(r"no\s+`?verdict`?.*line", lower) is not None
        or re.search(r"contains\s+no\s+`?verdict`?", lower) is not None
    )
    assert no_verdict_indicator, (
        "agents/reviewer.md Codex section must describe the soft-fail path "
        "(output with no VERDICT line) and instruct adding a visible finding. "
        "Current section does not clearly describe this case."
    )

    # The section must instruct adding a visible finding (not silently dropping).
    # Look for "visible", "nit", or "finding" near the soft-fail description.
    visible_indicator = (
        "visible" in lower
        or "[nit]" in section
        or "finding" in lower
    )
    assert visible_indicator, (
        "agents/reviewer.md Codex section must instruct adding a visible finding "
        "when the Codex script soft-fails. Never silently APPROVE. "
        "Current section does not make soft-fail visible."
    )

    # Must explicitly say never silently approve / never silently drop.
    never_silent = (
        "never silently" in lower
        or "not silently" in lower
        or "never silent" in lower
        or "silently drop" in lower
        or "silently approve" in lower
    )
    assert never_silent, (
        "agents/reviewer.md Codex section must explicitly prohibit silently "
        "dropping a soft-fail (e.g. 'Never silently drop this'). "
        "Current section does not contain this guard."
    )


# ---------------------------------------------------------------------------
# Test 9 — AGENTS.md updated description
# ---------------------------------------------------------------------------

def test_agents_md_updated_description():
    """
    REGRESSION (#49): AGENTS.md must reference 'codex-review' or
    'scripts/codex-review.mjs' in the 'Optional Codex review augmentation'
    section to reflect the new bundled-script approach.
    """
    text = _read(AGENTS_MD)
    # Find the section.
    m = re.search(
        r"## Optional Codex review augmentation.*?(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    assert m, (
        "AGENTS.md must contain an '## Optional Codex review augmentation' section."
    )
    section = m.group(0)
    assert "codex-review" in section or "scripts/codex-review.mjs" in section, (
        "AGENTS.md 'Optional Codex review augmentation' section must reference "
        "'codex-review' or 'scripts/codex-review.mjs' to describe the new "
        "bundled-script approach."
    )


# ---------------------------------------------------------------------------
# Test 10 — branch mode must normalize a remote-qualified default branch ref
# ---------------------------------------------------------------------------

def test_branch_mode_no_double_origin_prefix():
    """
    REGRESSION (#49 fix-pass): `runBranchMode` must normalize the defaultBranch
    argument so that both "main" and "origin/main" produce "--base origin/main",
    never the broken "--base origin/origin/main".

    Root cause: `git symbolic-ref --short refs/remotes/origin/HEAD` returns
    "origin/main" (already remote-qualified). Before the fix, the script did
    `origin/${defaultBranch}` unconditionally, yielding "origin/origin/main".

    This test has two complementary assertions:

    1. Source-level structural check (always runs, no Node required):
       - The script MUST contain a normalization expression that strips a leading
         "origin/" before building the base ref (e.g. `.replace(/^origin\\//, "")`).
       - The script must NOT contain a naked template literal that prepends
         "origin/" directly to the raw (un-normalized) `defaultBranch` variable
         (the exact anti-pattern that causes the double-prefix).

    On the unfixed code:
       - Assertion 1 fails because `.replace(/^origin\\//, "")` is absent.
       - Assertion 2 passes (the bug is present but the pattern check catches it
         via the absence of normalization, so together they definitively fail).
    After the fix:
       - Both assertions pass.
    """
    src = _read(SCRIPT_PATH)

    # 1. The script must contain a normalization that strips a leading "origin/".
    #    Accept any of the reasonable spellings:
    #      .replace(/^origin\//, "")     (double-escaped in a JS regex literal)
    #      .replace(/^origin\//, '')
    #      startsWith("origin/")         (if guarded by an if-branch strip)
    has_normalization = (
        re.search(r'replace\s*\(\s*/\^origin\\?\//', src) is not None
        or re.search(r'\.replace\s*\(\s*["\']origin/', src) is not None
        or re.search(r'startsWith\s*\(\s*["\']origin/', src) is not None
    )
    assert has_normalization, (
        "scripts/codex-review.mjs runBranchMode must normalize the defaultBranch "
        "argument by stripping any leading 'origin/' before constructing the "
        "--base ref. Expected a `.replace(/^origin\\//, \"\")` or equivalent guard. "
        "Without this, `git symbolic-ref --short refs/remotes/origin/HEAD` "
        "('origin/main') produces '--base origin/origin/main'."
    )

    # 2. The script must NOT apply `origin/${defaultBranch}` (or equivalent
    #    template literal) using the raw, un-normalized variable name.
    #    After the fix the intermediate normalized name is used instead.
    #
    #    We look for the template literal pattern "`origin/${defaultBranch}`"
    #    which is the exact double-prefix bug. The fixed code uses a normalized
    #    intermediate variable (e.g. normalizedBranch) instead of defaultBranch.
    has_naked_double_prefix = "`origin/${defaultBranch}`" in src
    assert not has_naked_double_prefix, (
        "scripts/codex-review.mjs still contains `origin/${defaultBranch}` — the "
        "un-normalized form that produces 'origin/origin/main' when the caller "
        "passes 'origin/main'. Replace with a normalized intermediate variable "
        "(e.g. `const normalizedBranch = defaultBranch.replace(/^origin\\//, \"\")`) "
        "and use `origin/${normalizedBranch}` instead."
    )


# ---------------------------------------------------------------------------
# Test 11 — node syntax check (optional)
# ---------------------------------------------------------------------------

def test_script_node_check():
    """
    Optional: run 'node --check scripts/codex-review.mjs' to verify syntax.
    Skips gracefully if node is not on PATH.
    """
    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH — skipping syntax check")

    result = subprocess.run(
        [node, "--check", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check scripts/codex-review.mjs failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test 12 — ticket #81 AC#2: Codex CHANGES_REQUESTED overrides own APPROVE
#
# RETROSPECTIVE REGRESSION COVERAGE, disclosed honestly per AGENTS.md: the
# override rule below was already implemented in agents/reviewer.md step 4
# (the "even if your own review alone would have been `APPROVE`" wording)
# and in emitFindingsAndVerdict()'s "findings.length > 0 -> CHANGES_REQUESTED"
# logic before ticket #81. No historical RED is claimed for these three
# tests — they are expected to (and did) pass on first run. Their protective
# value is pinning the folding rule and the script's verdict computation
# against future edits to reviewer.md step 4 / emitFindingsAndVerdict().
# ---------------------------------------------------------------------------

def test_reviewer_codex_changes_requested_overrides_own_approve():
    """
    RETROSPECTIVE (#81 AC#2): agents/reviewer.md's Codex section must state
    that Codex findings under VERDICT: CHANGES_REQUESTED are [blocking] and
    that the reviewer's final verdict is CHANGES_REQUESTED even if the
    reviewer's own review alone would have been APPROVE.
    """
    text = _read(REVIEWER_MD)
    section = _extract_codex_section(text)
    assert "[blocking]" in section, (
        "agents/reviewer.md Codex section must treat Codex findings under "
        "CHANGES_REQUESTED as [blocking]."
    )
    assert "even if your own review alone would have been" in section.lower(), (
        "agents/reviewer.md Codex section must explicitly state the override "
        "even if the reviewer's own review alone would have been APPROVE."
    )


def test_script_emits_changes_requested_when_findings_present(tmp_path):
    """
    RETROSPECTIVE (#81 AC#2, executable): codex-review.mjs working-tree mode,
    fed a stub companion that prints a finding line, must emit
    VERDICT: CHANGES_REQUESTED as the last non-empty stdout line — this is
    the mechanism agents/reviewer.md step 4 relies on to force the override.
    Skips gracefully if node/git are not on PATH (same pattern as
    test_script_node_check above).
    """
    import pytest
    node = shutil.which("node")
    git = shutil.which("git")
    if node is None or git is None:
        pytest.skip("node and/or git not found on PATH — skipping executable Codex script test")

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "foo.js").write_text("function foo() { return 1; }\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    (repo / "foo.js").write_text("function foo() { return 2; }\n", encoding="utf-8")

    stub = tmp_path / "stub-companion.mjs"
    stub.write_text(
        "process.stdout.write('src/foo.js:12 \\u2014 possible bug\\n');\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [node, str(SCRIPT_PATH), "working-tree", str(stub), "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"expected non-empty stdout, got: {result.stdout!r} stderr: {result.stderr!r}"
    assert lines[-1] == "VERDICT: CHANGES_REQUESTED"


def test_script_emits_approve_when_no_findings(tmp_path):
    """
    RETROSPECTIVE (#81 AC#2, executable): the mirrored case — a stub
    companion that prints no finding lines must yield VERDICT: APPROVE, so
    the override in reviewer.md step 4 only fires on genuine findings.
    """
    import pytest
    node = shutil.which("node")
    git = shutil.which("git")
    if node is None or git is None:
        pytest.skip("node and/or git not found on PATH — skipping executable Codex script test")

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "foo.js").write_text("function foo() { return 1; }\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    (repo / "foo.js").write_text("function foo() { return 2; }\n", encoding="utf-8")

    stub = tmp_path / "stub-companion.mjs"
    stub.write_text(
        "process.stdout.write('Looks fine, no issues found.\\n');\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [node, str(SCRIPT_PATH), "working-tree", str(stub), "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"expected non-empty stdout, got: {result.stdout!r} stderr: {result.stderr!r}"
    assert lines[-1] == "VERDICT: APPROVE"
