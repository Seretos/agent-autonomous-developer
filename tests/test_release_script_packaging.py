"""
Regression tests for ticket #81: the release workflow never staged
scripts/ (or hooks/) into the published plugin distribution, so
`agents/reviewer.md`'s Codex second-opinion pass — which invokes
`${CLAUDE_PLUGIN_ROOT}/scripts/codex-review.mjs` — always hits its
"script missing" fallback on a marketplace install, silently degrading
every review to a single verdict. Root cause: CONFIRMED packaging gap in
`.github/workflows/release.yml`'s staging step (not a missing
implementation — the script itself works).

Fix: stage scripts/ and hooks/ alongside skills/agents/assets, and add a
generic, fail-closed release-time gate (tools/check_plugin_payload.py) that
fails the release whenever any ${CLAUDE_PLUGIN_ROOT}/<path> reference in an
agent/skill/hook file is absent from the staged distribution — so this
class of bug can't recur silently for any future runtime file.

Behavioural requirements (see the approved plan for ticket #81):
  BR1 - the release payload contains scripts/ and hooks/.
  BR2 - every ${CLAUDE_PLUGIN_ROOT} reference is a shipped path (dev-time
        guard exercised directly against the real repo + real workflow).
  BR3 - the checker (tools/check_plugin_payload.py::verify_stage) fails
        closed against a real staged tree.
  BR4 - the release workflow actually invokes the gate, in the right place
        (after staging, before the push).
  BR5 - Codex CHANGES_REQUESTED overrides the reviewer's own APPROVE
        (already implemented; retrospective regression coverage only, see
        the BR5 section below — no historical RED is claimed).
"""

from __future__ import annotations

import pathlib
import re

import tools.check_plugin_payload as cpp

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
SCRIPT_PATH = REPO_ROOT / "scripts" / "codex-review.mjs"
HOOK_PATH = REPO_ROOT / "hooks" / "check-mcp-availability.mjs"
REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# BR1 - the release payload contains scripts/ and hooks/
# ---------------------------------------------------------------------------


def _staging_step_text() -> str:
    """Return just the 'Stage install tree and build release zip' step body,
    so assertions can't accidentally match unrelated parts of the workflow
    (e.g. the orphan-branch step, which also mentions $STAGE)."""
    text = _workflow_text()
    match = re.search(
        r"Stage install tree and build release zip.*?(?=\n {6}- name:|\Z)",
        text,
        re.DOTALL,
    )
    assert match, "release.yml must contain a 'Stage install tree and build release zip' step"
    return match.group(0)


def test_release_stages_scripts_dir():
    """
    REGRESSION (#81): the staging step must create $STAGE/scripts and copy
    scripts/ into it, so ${CLAUDE_PLUGIN_ROOT}/scripts/codex-review.mjs
    resolves on a marketplace install.
    """
    step = _staging_step_text()
    assert re.search(r'mkdir -p[^\n]*"\$STAGE/scripts"', step), (
        "release.yml staging step does not mkdir $STAGE/scripts — "
        "scripts/ is not staged into the install tree."
    )
    assert re.search(r'cp -a scripts/\.\s+"\$STAGE/scripts/"', step), (
        "release.yml staging step does not copy scripts/ into the install tree "
        "(expected a 'cp -a scripts/. \"$STAGE/scripts/\"' line)."
    )


def test_release_stages_hooks_dir():
    """
    REGRESSION (#81): the staging step must create $STAGE/hooks and copy
    hooks/ into it, so ${CLAUDE_PLUGIN_ROOT}/hooks/check-mcp-availability.mjs
    resolves on a marketplace install (same defect class as scripts/, same
    workflow step, fixed together per the approved plan).
    """
    step = _staging_step_text()
    assert re.search(r'mkdir -p[^\n]*"\$STAGE/hooks"', step), (
        "release.yml staging step does not mkdir $STAGE/hooks — "
        "hooks/ is not staged into the install tree."
    )
    assert re.search(r'cp -a hooks/\.\s+"\$STAGE/hooks/"', step), (
        "release.yml staging step does not copy hooks/ into the install tree "
        "(expected a 'cp -a hooks/. \"$STAGE/hooks/\"' line)."
    )


def test_referenced_runtime_scripts_exist_in_repo():
    """Sanity: the two files this ticket is about actually exist in the repo
    (root cause is packaging, not a missing implementation)."""
    assert SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist"
    assert HOOK_PATH.exists(), f"{HOOK_PATH} must exist"


def test_orphan_branch_step_copies_whole_stage_without_exclusion():
    """The orphan-branch step must copy the *entire* stage tree with no
    per-path exclusion, so BR1's fix (once landed) automatically reaches
    both the release branch and the zip — no second copy path to keep in
    sync."""
    text = _workflow_text()
    assert 'cp -a "$TMP"/. .' in text, (
        "release.yml's orphan-branch step must copy the whole staged tree "
        '(cp -a "$TMP"/. .) with no per-path filtering.'
    )
    assert "(cd \"$STAGE\" && zip -r" in text, (
        "release.yml must build the zip from the same $STAGE tree the "
        "orphan branch is populated from."
    )


# ---------------------------------------------------------------------------
# BR2 - every ${CLAUDE_PLUGIN_ROOT} reference is a shipped path
# ---------------------------------------------------------------------------


def test_all_referenced_plugin_root_paths_are_shipped():
    """
    REGRESSION (#81): every ${CLAUDE_PLUGIN_ROOT}/<path> reference found in
    agents/skills/hooks must resolve to a path the release workflow actually
    ships (top-level directory copied into $STAGE), unless explicitly listed
    in ALLOWED_UNSHIPPED (empty at landing).
    """
    references = cpp.discover_references(REPO_ROOT)
    # Guard against a vacuous pass: if discovery finds nothing, this test
    # would trivially "pass" without checking anything real.
    assert references, (
        "discover_references(REPO_ROOT) found zero ${CLAUDE_PLUGIN_ROOT} "
        "references — expected at least the scripts/codex-review.mjs and "
        "hooks/check-mcp-availability.mjs references. Discovery is broken."
    )

    shipped_top_level = cpp.staged_paths_from_workflow(_workflow_text())

    unshipped = []
    for reference in references:
        if reference.path in cpp.ALLOWED_UNSHIPPED:
            continue
        top_level = reference.path.split("/")[0]
        if top_level not in shipped_top_level:
            unshipped.append(reference)

    assert not unshipped, (
        "The following ${CLAUDE_PLUGIN_ROOT} references are not shipped by "
        "release.yml's staging step: "
        + ", ".join(f"{r.path} (referenced by {r.source_file})" for r in unshipped)
    )

    # The two concrete references this ticket is about must both be present
    # in the discovered set (and, by the assertion above, both shipped).
    discovered_paths = {r.path for r in references}
    assert "scripts/codex-review.mjs" in discovered_paths
    assert "hooks/check-mcp-availability.mjs" in discovered_paths


def test_allowed_unshipped_is_empty_at_landing():
    """
    ALLOWED_UNSHIPPED is the single documented escape hatch for a
    legitimately-unshipped reference. At landing (this ticket fixes both
    scripts/ and hooks/) there is no such reference, so the allowlist must
    be empty — any future entry is a deliberate, reviewed act.
    """
    assert cpp.ALLOWED_UNSHIPPED == frozenset(), (
        "ALLOWED_UNSHIPPED must be empty at landing; every referenced path "
        "is expected to be shipped now that scripts/ and hooks/ are staged."
    )


def test_discover_references_ignores_bare_plugin_root_mention():
    """
    The bare "`${CLAUDE_PLUGIN_ROOT}` points at *this*" prose in
    agents/reviewer.md (no trailing "/<path>") must not be treated as a file
    reference.
    """
    references = cpp.discover_references(REPO_ROOT)
    reviewer_refs = [r for r in references if r.source_file == "agents/reviewer.md"]
    # Only the one real, fenced-code-block reference should be found.
    assert all(r.path == "scripts/codex-review.mjs" for r in reviewer_refs), (
        f"Unexpected references discovered in agents/reviewer.md: {reviewer_refs!r}"
    )
    assert len(reviewer_refs) == 1


def test_discover_references_finds_reference_inside_fenced_code_block():
    """The reviewer.md:127 reference lives inside a ```bash fenced block —
    discovery must not be fooled by the surrounding Markdown fence."""
    references = cpp.discover_references(REPO_ROOT)
    assert any(
        r.path == "scripts/codex-review.mjs" and r.source_file == "agents/reviewer.md"
        for r in references
    )


def test_discover_references_finds_reference_inside_hooks_json():
    """hooks/hooks.json embeds the reference with JSON-escaped quotes
    (\\"${CLAUDE_PLUGIN_ROOT}/hooks/check-mcp-availability.mjs\\") — discovery
    must still find it."""
    references = cpp.discover_references(REPO_ROOT)
    assert any(
        r.path == "hooks/check-mcp-availability.mjs" and r.source_file == "hooks/hooks.json"
        for r in references
    )


def test_discover_references_walks_nested_skill_files():
    """discover_references must walk skills/*/SKILL.md (nested one level
    below skills/), not just a flat glob."""
    skill_files = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
    assert skill_files, "expected at least one skills/*/SKILL.md in this repo"
    scanned = {
        p.relative_to(REPO_ROOT).as_posix()
        for p in cpp._scanned_files(REPO_ROOT)  # noqa: SLF001 - internal, tested directly
    }
    for f in skill_files:
        assert f.relative_to(REPO_ROOT).as_posix() in scanned


def test_missing_in_repo_reference_reported_distinctly_from_not_staged(tmp_path):
    """A reference to a path that doesn't exist in the *repo* at all must be
    reported as MISSING_IN_REPO, distinctly from NOT_STAGED (present in repo,
    absent from stage)."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "x.md").write_text(
        "See `${CLAUDE_PLUGIN_ROOT}/scripts/does-not-exist.mjs` for details.\n",
        encoding="utf-8",
    )
    stage = tmp_path / "stage"
    (stage / "agents").mkdir(parents=True)
    (stage / "agents" / "x.md").write_text("staged copy\n", encoding="utf-8")

    problems = cpp.verify_stage(repo, stage)
    kinds_and_paths = {(p.kind, p.path) for p in problems}
    assert ("MISSING_IN_REPO", "scripts/does-not-exist.mjs") in kinds_and_paths


def test_allowed_unshipped_entry_suppresses_finding(tmp_path):
    """An ALLOWED_UNSHIPPED entry (tested against a synthetic set, not the
    real empty one) must suppress the NOT_STAGED finding for that path."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "x.md").write_text(
        "See `${CLAUDE_PLUGIN_ROOT}/tools/dev-only.mjs` for details.\n",
        encoding="utf-8",
    )
    (repo / "tools").mkdir()
    (repo / "tools" / "dev-only.mjs").write_text("// dev-only\n", encoding="utf-8")
    stage = tmp_path / "stage"
    (stage / "agents").mkdir(parents=True)
    (stage / "agents" / "x.md").write_text("staged copy\n", encoding="utf-8")
    # Note: stage has no tools/ dir at all — would ordinarily be NOT_STAGED.

    problems_without_allowlist = cpp.verify_stage(repo, stage, allowed_unshipped=frozenset())
    assert any(p.kind == "NOT_STAGED" and p.path == "tools/dev-only.mjs" for p in problems_without_allowlist)

    problems_with_allowlist = cpp.verify_stage(
        repo, stage, allowed_unshipped=frozenset({"tools/dev-only.mjs"})
    )
    assert not any(p.path == "tools/dev-only.mjs" for p in problems_with_allowlist)


# ---------------------------------------------------------------------------
# BR3 - the checker fails closed against a real staged tree
# ---------------------------------------------------------------------------


def _build_synthetic_repo_and_incomplete_stage(tmp_path):
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "x.md").write_text(
        "Run `${CLAUDE_PLUGIN_ROOT}/scripts/foo.mjs` to do the thing.\n",
        encoding="utf-8",
    )
    (repo / "scripts").mkdir()
    (repo / "scripts" / "foo.mjs").write_text("// stub\n", encoding="utf-8")

    stage = tmp_path / "stage"
    (stage / "agents").mkdir(parents=True)
    (stage / "agents" / "x.md").write_text(
        (repo / "agents" / "x.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Deliberately do NOT create stage/scripts/ — this is the defect BR3 must catch.
    return repo, stage


def test_checker_flags_reference_missing_from_stage(tmp_path):
    """
    Driving test for BR3: verify_stage() must report a referenced file that
    exists in the repo but is absent from the staged tree as NOT_STAGED.
    """
    repo, stage = _build_synthetic_repo_and_incomplete_stage(tmp_path)

    problems = cpp.verify_stage(repo, stage)

    assert any(
        p.kind == "NOT_STAGED" and p.path == "scripts/foo.mjs" for p in problems
    ), f"expected a NOT_STAGED problem for scripts/foo.mjs, got: {problems!r}"


def test_checker_reports_empty_problems_when_stage_is_complete(tmp_path):
    """Mirror positive case: when every referenced file (and every scanned
    source file) is present in the stage, verify_stage returns no problems."""
    repo, stage = _build_synthetic_repo_and_incomplete_stage(tmp_path)
    (stage / "scripts").mkdir()
    (stage / "scripts" / "foo.mjs").write_text("// stub\n", encoding="utf-8")

    problems = cpp.verify_stage(repo, stage)

    assert problems == []


def test_checker_flags_scanned_source_file_missing_from_stage(tmp_path):
    """If a scanned source file (e.g. an entire agents/ dir) is dropped from
    staging, verify_stage must report it directly — this is what stops the
    scan from going vacuously green when discovery itself finds nothing
    because its source directory wasn't staged."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "x.md").write_text("no references here\n", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    # agents/ entirely absent from the stage.

    problems = cpp.verify_stage(repo, stage)

    assert any(
        p.kind == "SOURCE_NOT_STAGED" and p.path == "agents/x.md" for p in problems
    ), f"expected a SOURCE_NOT_STAGED problem for agents/x.md, got: {problems!r}"


def test_checker_cli_exits_nonzero_and_prints_error_marker(tmp_path, capsys):
    """The CLI (main()) must exit non-zero and print an '::error::' line when
    problems exist — this is what actually fails the GitHub Actions step."""
    repo, stage = _build_synthetic_repo_and_incomplete_stage(tmp_path)

    exit_code = cpp.main(["--stage", str(stage), "--repo-root", str(repo)])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "::error::" in captured.out


def test_checker_cli_exits_zero_when_stage_is_complete(tmp_path, capsys):
    repo, stage = _build_synthetic_repo_and_incomplete_stage(tmp_path)
    (stage / "scripts").mkdir()
    (stage / "scripts" / "foo.mjs").write_text("// stub\n", encoding="utf-8")

    exit_code = cpp.main(["--stage", str(stage), "--repo-root", str(repo)])

    assert exit_code == 0


def test_checker_handles_empty_reference_set_without_crashing(tmp_path):
    """A repo with no ${CLAUDE_PLUGIN_ROOT} references anywhere must not
    crash verify_stage — it simply reports no reference problems."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "x.md").write_text("nothing to see here\n", encoding="utf-8")
    stage = tmp_path / "stage"
    (stage / "agents").mkdir(parents=True)
    (stage / "agents" / "x.md").write_text("nothing to see here\n", encoding="utf-8")

    problems = cpp.verify_stage(repo, stage)

    assert problems == []


def test_checker_end_to_end_against_real_repo_and_synthetic_full_stage(tmp_path):
    """
    End-to-end sanity check of the post-fix payload: build a synthetic stage
    that mirrors what release.yml now copies (skills/, agents/, assets/,
    scripts/, hooks/) from the *real* repo, and confirm verify_stage reports
    zero problems against it.
    """
    import shutil

    stage = tmp_path / "stage"
    for top in ("skills", "agents", "assets", "scripts", "hooks"):
        src = REPO_ROOT / top
        if src.is_dir():
            shutil.copytree(src, stage / top)

    problems = cpp.verify_stage(REPO_ROOT, stage)

    assert problems == [], f"expected zero problems, got: {problems!r}"


# ---------------------------------------------------------------------------
# BR4 - the release workflow actually invokes the gate, in the right place
# ---------------------------------------------------------------------------


def test_release_workflow_runs_payload_check_before_push():
    """
    REGRESSION (#81): release.yml must run
    'python3 tools/check_plugin_payload.py --stage ...' as its own step,
    strictly after the staging step and strictly before the orphan-branch
    push step — so a broken payload aborts the release before anything is
    pushed or tagged.
    """
    text = _workflow_text()

    stage_step_match = re.search(r"name: Stage install tree and build release zip", text)
    push_step_match = re.search(r"name: Push orphan release branch", text)
    assert stage_step_match, "release.yml must contain the staging step"
    assert push_step_match, "release.yml must contain the 'Push orphan release branch' step"

    check_match = re.search(r"tools/check_plugin_payload\.py[^\n]*--stage", text)
    assert check_match, (
        "release.yml must invoke tools/check_plugin_payload.py with --stage "
        "as its own workflow step."
    )

    assert stage_step_match.start() < check_match.start() < push_step_match.start(), (
        "the payload-check step must run strictly after staging and strictly "
        "before the orphan-branch push."
    )


def test_release_workflow_payload_check_uses_stage_output_not_source_tree():
    """The check must be pointed at the *staged* tree
    (${{ steps.stage.outputs.stage }}), never the source tree — checking the
    stage against itself would pass vacuously."""
    text = _workflow_text()
    check_line_match = re.search(
        r"tools/check_plugin_payload\.py[^\n]*", text
    )
    assert check_line_match, "release.yml must invoke tools/check_plugin_payload.py"
    line = check_line_match.group(0)
    assert "steps.stage.outputs.stage" in line, (
        "the payload-check invocation must pass --stage "
        "\"${{ steps.stage.outputs.stage }}\", not a hardcoded or source path."
    )


def test_release_workflow_payload_check_is_not_soft_failed():
    """The payload-check step must not be neutered with continue-on-error or
    a shell-level '|| true' — it must genuinely block the release."""
    text = _workflow_text()
    check_step_match = re.search(
        r"- name: Verify referenced plugin files are staged.*?(?=\n {6}- name:|\Z)",
        text,
        re.DOTALL,
    )
    assert check_step_match, "could not locate the payload-check step block"
    step_block = check_step_match.group(0)
    assert "continue-on-error" not in step_block
    assert "|| true" not in step_block


# ---------------------------------------------------------------------------
# BR5 - Codex CHANGES_REQUESTED overrides the reviewer's own APPROVE
#
# RETROSPECTIVE REGRESSION COVERAGE, disclosed honestly per AGENTS.md: this
# behaviour was already implemented in agents/reviewer.md step 4 and
# scripts/codex-review.mjs's emitFindingsAndVerdict() before this ticket. No
# historical RED is claimed for these tests — they are expected to (and did)
# pass on first run. Their protective value is pinning the folding rule and
# the script's verdict computation against future edits.
# ---------------------------------------------------------------------------


def _extract_codex_section(text: str) -> str:
    match = re.search(
        r"## Optional.*?Codex second opinion.*?(?=\n## |\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    assert match, "agents/reviewer.md must contain an 'Optional — Codex second opinion' section"
    return match.group(0)


def test_reviewer_codex_changes_requested_overrides_own_approve():
    """RETROSPECTIVE: agents/reviewer.md step 4 must state that a Codex
    VERDICT: CHANGES_REQUESTED forces the reviewer's own final verdict to
    CHANGES_REQUESTED even when the reviewer's own review alone would have
    been APPROVE."""
    text = REVIEWER_MD.read_text(encoding="utf-8")
    section = _extract_codex_section(text)
    lower = section.lower()
    assert "[blocking]" in section, (
        "Codex section must say Codex findings under CHANGES_REQUESTED are treated as [blocking]."
    )
    assert "even if your own review alone would have been" in lower, (
        "Codex section must explicitly state the override even when the reviewer's "
        "own review alone would have been APPROVE."
    )


# NOTE (#81 fix pass, de-duplication): the two executable Codex-verdict stub
# tests (VERDICT: CHANGES_REQUESTED when findings are present, VERDICT:
# APPROVE when none are) used to be duplicated here. Per AGENTS.md, BR5 (the
# AC#2 Codex-override coverage) belongs in tests/test_reviewer_codex_scripts.py
# — that file already owns scripts/codex-review.mjs + reviewer.md Codex-section
# coverage from ticket #49 — so the executable copies now live there only:
# test_script_emits_changes_requested_when_findings_present and
# test_script_emits_approve_when_no_findings.
