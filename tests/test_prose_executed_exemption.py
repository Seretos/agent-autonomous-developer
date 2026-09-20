"""
Ticket #123 -- a requirement whose only executor is a model reading a prose
file must be declarable `none`/`ci-evidence` without the #108 rules firing.

  R1/R2: scripts/critic/prose-role-check.py classifies every hunk of a unified
         diff PROSE or CODE by role (default deny: everything outside the role
         table is CODE); exit 0 = all prose, 1 = any code, 2 = usage/parse.
  R3:    the #122-shaped fixture plan replays through both real packagers, and
         the prose-executed exemption is assembled into exactly the two lens
         blocks that own it (plan-critic `untestable`, test-critic `tautology`).

Assertions are against script output and generated packager output -- never
against a sentence in agents/*.md, SKILL.md or AGENTS.md.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CRITIC = REPO_ROOT / "scripts" / "critic"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "prose-executed"

ROLE_CHECK = CRITIC / "prose-role-check.py"
PLAN_CRITIC_PACKAGE = CRITIC / "plan-critic-package.sh"
TEST_CRITIC_PACKAGE = CRITIC / "test-critic-package.sh"

SPEC = FIXTURES / "spec.md"
SCOPE = FIXTURES / "scope.md"
PLAN = FIXTURES / "plan.md"
TESTS_DIFF = FIXTURES / "tests.diff"
PROSE_ONLY_DIFF = FIXTURES / "prose-only.diff"
MIXED_CODE_DIFF = FIXTURES / "mixed-code.diff"

REQUIRE_SHELL_TOOLING = os.environ.get("ADEV_REQUIRE_SHELL_TOOLING") == "1"


def _resolve_bash():
    if sys.platform == "win32":
        candidate = r"C:\Program Files\Git\bin\bash.exe"
        return candidate if pathlib.Path(candidate).is_file() else None
    return shutil.which("bash")


BASH = _resolve_bash()


def _require_bash() -> None:
    if BASH is not None:
        return
    if REQUIRE_SHELL_TOOLING:
        raise RuntimeError("bash not available on PATH and ADEV_REQUIRE_SHELL_TOOLING=1")
    pytest.skip("bash not available on this machine")


def _run_bash(script: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    _require_bash()
    return subprocess.run(
        [BASH, str(script), *args], capture_output=True, text=True, encoding="utf-8"
    )


def _role_check(*args: str, stdin=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROLE_CHECK), *args],
        capture_output=True, text=True, encoding="utf-8", input=stdin,
    )


# ---------------------------------------------------------------------------
# Diff synthesis: ranges are located in the REAL scripts at test time.
# ---------------------------------------------------------------------------

def _heredoc_body_range(script: pathlib.Path, delim: str):
    """1-based inclusive line range of the body of `<<'DELIM'` ... `DELIM`."""
    lines = script.read_text(encoding="utf-8").splitlines()
    opener = next(i for i, l in enumerate(lines, 1) if f"<<'{delim}'" in l)
    closer = next(i for i, l in enumerate(lines, 1) if i > opener and l.strip() == delim)
    return opener + 1, closer - 1


def _hunk(path: str, start: int, count: int) -> str:
    """One unified-diff file section whose single hunk has `count` new-side
    lines starting at `start` (count-1 context lines and one added line)."""
    body = "".join(" context line\n" for _ in range(count - 1)) + "+added line\n"
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -{start},{count - 1} +{start},{count} @@\n"
        f"{body}"
    )


def _deletion_hunk(path: str, start: int) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -{start},2 +{start - 1},0 @@\n"
        "-removed line one\n"
        "-removed line two\n"
    )


def _lines(stdout: str, verdict: str):
    return [l for l in stdout.splitlines() if l.split(" ", 1)[0] == verdict]


# ---------------------------------------------------------------------------
# R1 -- hunk-level prose/code classification
# ---------------------------------------------------------------------------

def test_prose_paths_and_package_heredoc_hunk_are_all_prose(tmp_path):
    """Driving test for R1. Today the script does not exist, so stdout is empty
    and the per-hunk assertions fail (not merely a missing-file exit code)."""
    start, end = _heredoc_body_range(PLAN_CRITIC_PACKAGE, "LENS_UNTESTABLE")
    hs, he = start + 2, start + 4
    assert he <= end
    diff = _hunk("agents/planner.md", 40, 3) + _hunk(
        "scripts/critic/plan-critic-package.sh", hs, he - hs + 1
    )
    diff_file = tmp_path / "prose.diff"
    diff_file.write_text(diff, encoding="utf-8")

    result = _role_check("--diff", str(diff_file), "--repo-root", str(REPO_ROOT))

    assert result.returncode == 0, result.stdout + result.stderr
    prose = _lines(result.stdout, "PROSE")
    assert any("agents/planner.md:40-42" in l for l in prose), result.stdout
    assert any(f"scripts/critic/plan-critic-package.sh:{hs}-{he}" in l for l in prose), result.stdout
    assert not _lines(result.stdout, "CODE"), result.stdout


def test_diff_can_be_read_from_stdin():
    result = _role_check("--diff", "-", "--repo-root", str(REPO_ROOT),
                         stdin=_hunk("skills/process-ticket/SKILL.md", 5, 2))
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("skills/process-ticket/SKILL.md:5-6" in l for l in _lines(result.stdout, "PROSE"))


def test_fixture_prose_only_diff_is_all_prose():
    result = _role_check("--diff", str(PROSE_ONLY_DIFF), "--repo-root", str(REPO_ROOT))
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_lines(result.stdout, "PROSE")) == 2


def test_diff_without_hunks_and_unparseable_diff_exit_2(tmp_path):
    # --repo-root is always supplied: exit 2 must come from the diff content,
    # not from a script that merely requires the option.
    empty = tmp_path / "empty.diff"
    empty.write_text("", encoding="utf-8")
    garbage = tmp_path / "garbage.diff"
    garbage.write_text("this is not a diff\n@@ nonsense @@\n", encoding="utf-8")
    # A missing script also exits 2 (interpreter cannot open it); require the
    # script so that exit code cannot be mistaken for diff handling.
    assert ROLE_CHECK.is_file(), "scripts/critic/prose-role-check.py does not exist"
    for diff_file in (empty, garbage):
        result = _role_check("--diff", str(diff_file), "--repo-root", str(REPO_ROOT))
        assert result.returncode == 2, (diff_file.name, result.stdout, result.stderr)
        assert result.stderr.strip(), f"{diff_file.name}: exit 2 must explain itself on stderr"
        assert not _lines(result.stdout, "PROSE"), result.stdout


def test_prose_path_missing_under_repo_root_is_still_prose(tmp_path):
    result = _role_check("--diff", "-", "--repo-root", str(tmp_path),
                         stdin=_hunk("agents/does-not-exist.md", 1, 2))
    assert result.returncode == 0, result.stdout + result.stderr
    prose = _lines(result.stdout, "PROSE")
    assert any("agents/does-not-exist.md:1-2" in l for l in prose), result.stdout
    assert not _lines(result.stdout, "CODE"), result.stdout


def test_claude_and_agents_md_at_any_depth_and_constraints_are_prose():
    diff = (_hunk("AGENTS.md", 1, 2) + _hunk("sub/dir/CLAUDE.md", 1, 2)
            + _hunk("scripts/critic/test-critic-constraints.md", 1, 2)
            + _hunk("scripts/critic/plan-critic-system-prompt.txt", 1, 2))
    result = _role_check("--diff", "-", "--repo-root", str(REPO_ROOT), stdin=diff)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_lines(result.stdout, "PROSE")) == 4


# ---------------------------------------------------------------------------
# R2 -- the exemption is refused for executable code (#108 case stays)
# ---------------------------------------------------------------------------

def test_code_hunks_exit_1_and_are_named_while_prose_hunk_stays_prose():
    """Driving test for R2: merge.py hunk (fixture) + a hunk in the `set -euo
    pipefail` region of the real package script + one prose hunk."""
    pkg = PLAN_CRITIC_PACKAGE.read_text(encoding="utf-8").splitlines()
    set_line = next(i for i, l in enumerate(pkg, 1) if l.strip() == "set -euo pipefail")
    diff = (MIXED_CODE_DIFF.read_text(encoding="utf-8")
            + _hunk("scripts/critic/plan-critic-package.sh", set_line, 2))

    result = _role_check("--diff", "-", "--repo-root", str(REPO_ROOT), stdin=diff)

    assert result.returncode == 1, result.stdout + result.stderr
    code = _lines(result.stdout, "CODE")
    assert any("scripts/critic/plan-critic-merge.py:5-7" in l for l in code), result.stdout
    assert any(f"scripts/critic/plan-critic-package.sh:{set_line}-{set_line + 1}" in l
               for l in code), result.stdout
    assert any("agents/reviewer.md:30-32" in l for l in _lines(result.stdout, "PROSE")), result.stdout
    # Format: `CODE <path>:<start>-<end> <reason>` -- every CODE line names why.
    for line in _lines(result.stdout, "CODE"):
        parts = line.split(None, 2)
        assert len(parts) == 3 and parts[2].strip(), f"CODE line without a reason: {line!r}"


def test_pure_deletion_in_package_script_fails_closed():
    start, _ = _heredoc_body_range(PLAN_CRITIC_PACKAGE, "LENS_UNTESTABLE")
    result = _role_check("--diff", "-", "--repo-root", str(REPO_ROOT),
                         stdin=_deletion_hunk("scripts/critic/plan-critic-package.sh", start + 3))
    assert result.returncode == 1, result.stdout + result.stderr
    assert _lines(result.stdout, "CODE"), result.stdout


def test_readme_and_unknown_paths_are_code_by_default_deny():
    for path in ("README.md", "tests/test_something.py", "hooks/check-no-background.mjs"):
        result = _role_check("--diff", "-", "--repo-root", str(REPO_ROOT),
                             stdin=_hunk(path, 1, 2))
        assert result.returncode == 1, (path, result.stdout, result.stderr)
        assert _lines(result.stdout, "CODE"), (path, result.stdout)


# ---------------------------------------------------------------------------
# R3 -- the #122-shaped plan replays through both real packagers
# ---------------------------------------------------------------------------

LENS_BLOCK_MARKER = "This run's lens:"
EXEMPTION_RE = re.compile(r"prose-executed", re.IGNORECASE)

# Anchors of the two #108 clauses the exemption must live inside. They are the
# same strings tests/test_untested_symptom_is_critical.py already relies on.
TAUTOLOGY_CLAUSE_ANCHOR = "the acceptance criterion is exercised by no test"
UNTESTABLE_CLAUSE_ANCHOR = "A related carve-out (ticket #108)"
# The #108 exemption-list siblings the new item joins (not a new clause).
SIBLING_EXEMPTIONS = ("Substitute execution", "ci-evidence")


def _lens_block_only(package_text: str) -> str:
    return package_text[package_text.index(LENS_BLOCK_MARKER):]


def _paragraph_containing(text: str, needle: str) -> str:
    paras = re.split(r"\n\s*\n", text)
    hits = [p for p in paras if needle in p]
    assert len(hits) == 1, f"expected exactly one paragraph holding {needle!r}, got {len(hits)}"
    return hits[0]


def _plan_package(tmp_path, lens, plan=PLAN):
    out = tmp_path / f"plan-package-{lens}-{plan.stem}.txt"
    result = _run_bash(PLAN_CRITIC_PACKAGE, str(SPEC), str(SCOPE), str(plan), lens, str(out))
    return result, out


def _test_package(tmp_path, plan=PLAN):
    out = tmp_path / f"test-package-{plan.stem}.txt"
    result = _run_bash(TEST_CRITIC_PACKAGE, str(plan), str(TESTS_DIFF), "tautology", str(out))
    return result, out


def _prose_executed_paths(plan_text: str):
    """Paths named on a plan's `Prose-executed:` lines (text before the first
    em-dash), parsed the way a reviewer would."""
    paths = []
    for m in re.finditer(r"^\s*Prose-executed:\s*(.+?)\s+—", plan_text, re.MULTILINE):
        paths += re.findall(r"[\w./-]+\.(?:md|txt|sh|py|mjs|json)", m.group(1))
    return paths


def _role_verdict_for_declared_paths(plan_text: str):
    paths = _prose_executed_paths(plan_text)
    assert paths, "fixture plan declares no Prose-executed paths"
    diff = "".join(_hunk(p, 1, 2) for p in paths)
    return _role_check("--diff", "-", "--repo-root", str(REPO_ROOT), stdin=diff)


def _assert_exemption_names_the_mechanical_gate(paragraph: str, lens: str) -> None:
    """The exemption's condition must refer to the mechanical role check: the
    paragraph must name a script that exists under scripts/critic/, so a
    bare token insertion that refers to nothing fails. Residual inherent
    weakness (stated, not hidden): no packager can prove a model obeys the
    sentence, so wording that names the script but still demands the opposite
    is not caught here -- that is a review-time judgement."""
    named = re.findall(r"[\w./-]*prose-role-check\.py", paragraph)
    assert named, f"{lens}: exemption does not name the mechanical gate prose-role-check.py"
    for ref in named:
        assert (CRITIC / pathlib.PurePosixPath(ref).name).is_file(), (
            f"{lens}: names {ref} but it does not exist under scripts/critic/"
        )


def test_exemption_sits_inside_the_108_exemption_list_of_the_owning_lens(tmp_path):
    """Driving test for R3. Assembly is checked structurally, in the paragraph
    that carries each #108 clause: the prose-executed item must be a member of
    the SAME exemption list as the existing #108 exemptions (narrowed in place,
    not a free-floating extra rule), after the `critical` instruction it
    exempts from, and must not be in any other lens or in PARTs 2-4.

    Inherent limit: the paragraph is prose a model reads; no packager can
    prove the model honours it. What this pins is that the exemption cannot
    exist merely as a token elsewhere in the block."""
    tc, tc_out = _test_package(tmp_path)
    assert tc.returncode == 0, tc.stderr
    taut_block = _lens_block_only(tc_out.read_text(encoding="utf-8"))
    taut_para = _paragraph_containing(taut_block, TAUTOLOGY_CLAUSE_ANCHOR)
    assert "critical" in taut_para
    assert EXEMPTION_RE.search(taut_para), (
        "prose-executed exemption is not inside the tautology #108 clause's exemption list"
    )
    for sibling in SIBLING_EXEMPTIONS:
        assert sibling in taut_para
    assert taut_para.index("critical") < EXEMPTION_RE.search(taut_para).start()
    _assert_exemption_names_the_mechanical_gate(taut_para, "tautology")

    blocks, heads = {}, {}
    for lens in ("missed", "misread", "untestable", "simplifier"):
        result, out = _plan_package(tmp_path, lens)
        assert result.returncode == 0, (lens, result.stderr)
        text = out.read_text(encoding="utf-8")
        blocks[lens] = _lens_block_only(text)
        # PART 1 legitimately embeds the plan (which uses the declaration);
        # PARTs 2-4 (constraints, scope, ...) must not carry the exemption.
        heads[lens] = text[text.index("PART 2"): text.index(LENS_BLOCK_MARKER)]

    unt_para = _paragraph_containing(blocks["untestable"], UNTESTABLE_CLAUSE_ANCHOR)
    assert "critical" in unt_para
    assert EXEMPTION_RE.search(unt_para), (
        "prose-executed exemption is not inside the untestable #108 carve-out's exemption list"
    )
    assert "Substitute execution" in unt_para and "ci-evidence" in unt_para
    _assert_exemption_names_the_mechanical_gate(unt_para, "untestable")

    for lens in ("missed", "misread", "simplifier"):
        assert not EXEMPTION_RE.search(blocks[lens]), f"{lens} lens block must not carry it"
    for lens, head in heads.items():
        assert not EXEMPTION_RE.search(head), f"{lens}: exemption leaked into PARTs 2-4"


def test_108_blocking_wording_for_executable_code_is_untouched_in_both_lenses(tmp_path):
    """Control (may already pass): the exemption narrows #108, it must not
    soften it -- the critical instructions stay in the lens blocks."""
    tc, tc_out = _test_package(tmp_path)
    assert tc.returncode == 0, tc.stderr
    taut = _paragraph_containing(_lens_block_only(tc_out.read_text(encoding="utf-8")),
                                 TAUTOLOGY_CLAUSE_ANCHOR)
    assert "`critical` finding, layer `plan`" in taut
    result, out = _plan_package(tmp_path, "untestable")
    assert result.returncode == 0, result.stderr
    unt = _paragraph_containing(_lens_block_only(out.read_text(encoding="utf-8")),
                                UNTESTABLE_CLAUSE_ANCHOR)
    assert "`critical` finding, kind `gap`" in unt


def test_plan_critic_parts_1_to_4_stay_byte_identical_across_lenses(tmp_path):
    """Control (may already pass): the exemption is lens-local, so the shared
    prefix must not move."""
    texts = {}
    for lens in ("missed", "misread", "untestable", "simplifier"):
        result, out = _plan_package(tmp_path, lens)
        assert result.returncode == 0, (lens, result.stderr)
        text = out.read_text(encoding="utf-8")
        texts[lens] = text[: text.index(LENS_BLOCK_MARKER)]
    assert len(set(texts.values())) == 1


def test_declared_paths_carry_the_executable_vs_prose_discriminator(tmp_path):
    """The packagers cannot judge a declaration (no diff exists at that time),
    so the prose/executable discriminator lives in prose-role-check.py. Replay
    the fixture plan's own `Prose-executed:` declaration: its named paths are
    prose (exit 0); the SAME declaration re-pointed at executable code is
    refused (exit 1), while both plans are equally accepted by both packagers
    -- which is exactly why the reviewer's role check, not the packager, is
    the gate."""
    plan_text = PLAN.read_text(encoding="utf-8")
    assert _role_verdict_for_declared_paths(plan_text).returncode == 0

    code_plan = tmp_path / "plan-code.md"
    code_plan.write_text(
        plan_text.replace("Prose-executed: agents/planner.md",
                          "Prose-executed: scripts/critic/plan-critic-merge.py"),
        encoding="utf-8")
    verdict = _role_verdict_for_declared_paths(code_plan.read_text(encoding="utf-8"))
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert any("plan-critic-merge.py" in l for l in _lines(verdict.stdout, "CODE"))

    for plan in (PLAN, code_plan):
        assert _test_package(tmp_path, plan)[0].returncode == 0
        assert _plan_package(tmp_path, "untestable", plan)[0].returncode == 0
