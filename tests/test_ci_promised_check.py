"""
Ticket #122 — Phase 6 must not post ``ci-green`` on run conclusions alone.

Requirements covered (ids from the plan's test strategy):

* R1 - #347 replay: a job added to a workflow that has no run at the PR head
  is a gap even though every run handed in is green.
* R2 - a package that adds no CI job is ``ok`` (no extra round).
* R3 - only a *successful* run for the workflow that gained the job clears it.
* R4 - unusable input never yields ``verdict: ok`` (exit 1, stderr).
* R5 - the script is model-free, allowlisted in SKILL.md, consulted on both
  ``ci-green`` lanes, and discovered by the release-payload gate.

Exit-code contract of ``scripts/ci-promised-check.py``: 0 = ok, 2 = gap,
1 = unusable input (never ok). Phase 6's routing of exit 1 (retry once, then
``blocked``) is skill prose and is deliberately not pinned by wording here.
"""

import json
import pathlib
import re
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci-promised-check.py"
SKILL = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

sys.path.insert(0, str(REPO_ROOT))

RELEASE_BASE = """\
name: Release
on:
  workflow_dispatch:
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: echo release
"""

RELEASE_WITH_SMOKE = RELEASE_BASE + """\
  smoke:
    runs-on: ubuntu-latest
    steps:
      - run: echo smoke
"""

RELEASE_STEP_TWEAK = RELEASE_BASE.replace("echo release", "echo release again")


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    )


def _head(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_repo(tmp_path, base_files, head_files, deleted=()):
    """Repo with branch ``main`` (base_files) and a feature commit on top."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")

    def write(files):
        for rel, body in files.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

    write({"README.md": "x\n", **base_files})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feature")
    write(head_files)
    for rel in deleted:
        (repo / rel).unlink()
    write({"CHANGE.txt": "c\n"})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "feature")
    return repo


def _run(repo, runs, *, base="main", raw=None, payload_extra=None):
    payload = {"worktree": str(repo), "base": base, "head": _head(repo),
               "runs": runs}
    if payload_extra is not None:
        payload = payload_extra
    stdin = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(SCRIPT)], input=stdin,
        capture_output=True, text=True, timeout=60,
    )


def _run_named(name, conclusion="success"):
    return {"name": name, "status": "completed", "conclusion": conclusion,
            "head_sha": "x", "url": "https://example.invalid/run"}


# --- R1: the #347 replay ----------------------------------------------------

def test_dispatch_only_workflow_with_added_job_is_a_gap(tmp_path):
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": RELEASE_BASE},
        {".github/workflows/release.yml": RELEASE_WITH_SMOKE},
    )
    res = _run(repo, [_run_named("lint")])
    assert res.returncode == 2, res.stdout + res.stderr
    assert "verdict: gap" in res.stdout
    assert ".github/workflows/release.yml" in res.stdout
    assert "smoke" in res.stdout


def test_brand_new_workflow_file_with_no_run_is_a_gap(tmp_path):
    repo = _make_repo(
        tmp_path, {},
        {".github/workflows/extra.yml": RELEASE_WITH_SMOKE},
    )
    res = _run(repo, [_run_named("lint")])
    assert res.returncode == 2, res.stdout + res.stderr
    assert "verdict: gap" in res.stdout
    assert ".github/workflows/extra.yml" in res.stdout


# --- R2: no added job -> ok --------------------------------------------------

def test_no_added_job_is_ok(tmp_path):
    # Case 1: no workflow changed at all.
    repo = _make_repo(tmp_path, {}, {"src/a.txt": "a\n"})
    res = _run(repo, [])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verdict: ok" in res.stdout
    assert "gap" not in res.stdout.replace("verdict: ok", "")


def test_workflow_changed_without_added_job_is_ok(tmp_path):
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": RELEASE_BASE},
        {".github/workflows/release.yml": RELEASE_STEP_TWEAK},
    )
    res = _run(repo, [])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verdict: ok" in res.stdout


def test_deleted_workflow_contributes_no_added_jobs(tmp_path):
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": RELEASE_WITH_SMOKE},
        {},
        deleted=[".github/workflows/release.yml"],
    )
    res = _run(repo, [])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verdict: ok" in res.stdout


# --- R3: a successful run for that workflow clears it -----------------------

@pytest.mark.parametrize(
    "runs, expected_rc",
    [
        ([_run_named("Release", "success")], 0),
        ([], 2),
        ([_run_named("Release", None)], 2),
        ([_run_named("Release", "cancelled")], 2),
        ([_run_named("Release", "failure")], 2),
    ],
    ids=["success", "missing", "null-conclusion", "cancelled", "failure"],
)
def test_added_job_needs_a_successful_run_for_that_workflow(
        tmp_path, runs, expected_rc):
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": RELEASE_BASE},
        {".github/workflows/release.yml": RELEASE_WITH_SMOKE},
    )
    res = _run(repo, runs)
    assert res.returncode == expected_rc, res.stdout + res.stderr
    # `python <missing file>` itself exits 2, so pin the verdict line too.
    verdict = "verdict: ok" if expected_rc == 0 else "verdict: gap"
    assert verdict in res.stdout


def test_run_name_match_is_case_insensitive(tmp_path):
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": RELEASE_BASE},
        {".github/workflows/release.yml": RELEASE_WITH_SMOKE},
    )
    res = _run(repo, [_run_named("RELEASE", "success")])
    assert res.returncode == 0, res.stdout + res.stderr


def test_workflow_without_name_is_matched_by_its_path(tmp_path):
    no_name = RELEASE_WITH_SMOKE.replace("name: Release\n", "")
    base = RELEASE_BASE.replace("name: Release\n", "")
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": base},
        {".github/workflows/release.yml": no_name},
    )
    ok = _run(repo, [_run_named(".github/workflows/release.yml")])
    assert ok.returncode == 0, ok.stdout + ok.stderr
    gap = _run(repo, [_run_named("Release")])
    assert gap.returncode == 2, gap.stdout + gap.stderr


# --- R4: unusable input never reports ok ------------------------------------

def test_unusable_input_never_reports_ok(tmp_path):
    repo = _make_repo(
        tmp_path,
        {".github/workflows/release.yml": RELEASE_BASE},
        {".github/workflows/release.yml": RELEASE_WITH_SMOKE},
    )
    cases = {
        "malformed-json": _run(repo, [], raw="{not json"),
        "missing-key": _run(repo, [], payload_extra={
            "worktree": str(repo), "base": "main", "runs": []}),
        "unresolvable-base": _run(repo, [], base="no-such-branch"),
    }
    for label, res in cases.items():
        assert res.returncode == 1, (label, res.stdout, res.stderr)
        assert "verdict: ok" not in res.stdout, label
        assert res.stderr.strip(), f"{label}: diagnostic must go to stderr"


def test_workflow_without_jobs_block_contributes_no_jobs(tmp_path):
    repo = _make_repo(
        tmp_path, {},
        {".github/workflows/empty.yml": "name: Empty\non: push\n"},
    )
    res = _run(repo, [])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verdict: ok" in res.stdout


# --- R5: model-free, allowlisted, consulted on both green lanes -------------

def _phase6(text):
    m = re.search(r"^## Phase 6\b.*?(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert m, "Phase 6 section not found"
    return m.group(0)


def test_script_is_model_free():
    assert SCRIPT.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    code = text.split('"""', 2)[-1]
    code = "\n".join(l for l in code.splitlines()
                     if not l.lstrip().startswith("#"))
    # subprocess is deliberately allowed: the script shells out to git.
    for token in ("claude", "anthropic", "requests", "urllib"):
        assert token not in code.lower(), \
            f"ci-promised-check.py must not invoke a model / network ({token})"


def test_script_is_allowlisted_and_consulted_on_both_green_lanes():
    text = SKILL.read_text(encoding="utf-8")
    m = re.search(r"Delegate everything.*?Nothing else", text, re.DOTALL)
    assert m and "ci-promised-check.py" in m.group(0)
    assert _phase6(text).count("ci-promised-check.py") >= 2


def test_payload_gate_discovers_the_new_script():
    from tools.check_plugin_payload import discover_references
    paths = {r.path for r in discover_references(REPO_ROOT)}
    assert "scripts/ci-promised-check.py" in paths
