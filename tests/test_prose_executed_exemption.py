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
    empty = tmp_path / "empty.diff"
    empty.write_text("", encoding="utf-8")
    assert _role_check("--diff", str(empty)).returncode == 2
    garbage = tmp_path / "garbage.diff"
    garbage.write_text("this is not a diff\n@@ nonsense @@\n", encoding="utf-8")
    assert _role_check("--diff", str(garbage)).returncode == 2


def test_prose_path_missing_under_repo_root_is_still_prose(tmp_path):
    result = _role_check("--diff", "-", "--repo-root", str(tmp_path),
                         stdin=_hunk("agents/does-not-exist.md", 1, 2))
    assert result.returncode == 0, result.stdout + result.stderr


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


def _lens_block_only(package_text: str) -> str:
    return package_text[package_text.index(LENS_BLOCK_MARKER):]


def _plan_package(tmp_path, lens):
    out = tmp_path / f"plan-package-{lens}.txt"
    result = _run_bash(PLAN_CRITIC_PACKAGE, str(SPEC), str(SCOPE), str(PLAN), lens, str(out))
    return result, out


def test_prose_executed_exemption_lands_in_exactly_the_two_owning_lens_blocks(tmp_path):
    """Driving test for R3. Both packagers already accept the fixture plan
    (exit 0); the new behaviour is where the exemption is assembled."""
    tc_out = tmp_path / "test-package.txt"
    tc = _run_bash(TEST_CRITIC_PACKAGE, str(PLAN), str(TESTS_DIFF), "tautology", str(tc_out))
    assert tc.returncode == 0, tc.stderr
    assert EXEMPTION_RE.search(_lens_block_only(tc_out.read_text(encoding="utf-8"))), (
        "tautology lens block carries no prose-executed exemption"
    )

    blocks = {}
    for lens in ("missed", "misread", "untestable", "simplifier"):
        result, out = _plan_package(tmp_path, lens)
        assert result.returncode == 0, (lens, result.stderr)
        blocks[lens] = _lens_block_only(out.read_text(encoding="utf-8"))

    assert EXEMPTION_RE.search(blocks["untestable"]), (
        "untestable lens block carries no prose-executed exemption"
    )
    for lens in ("missed", "misread", "simplifier"):
        assert not EXEMPTION_RE.search(blocks[lens]), f"{lens} lens block must not carry it"


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


def test_fixture_anchor_survives_verbatim_inside_part_1(tmp_path):
    """Additional coverage (may already pass): the #108 anchor precondition
    accepts the fixture plan and carries the anchor into PART 1."""
    anchor = ("No available assertion executes such a requirement; any assertion is a "
              "string comparison.")
    out = tmp_path / "test-package.txt"
    result = _run_bash(TEST_CRITIC_PACKAGE, str(PLAN), str(TESTS_DIFF), "tautology", str(out))
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert anchor in text[text.index("PART 1"): text.index("PART 2")]
