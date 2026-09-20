"""
Ticket #122 — Phase 6 must not post ``ci-green`` on run conclusions alone.

Requirements covered (ids from the plan's test strategy):

* R1 - #347 replay: a job added to a workflow that has no run at the PR head
  is a gap even though every run handed in is green.
* R2 - a package that adds no CI job is ``ok`` (no extra round).
* R3 - only a *successful* run for the workflow that gained the job clears it.
* R4 - unusable input never yields ``verdict: ok`` (exit 1, stderr).
* R5 - the script is offline/model-free (AST: no network/model imports, every
  subprocess call is a literal ``["git", ...]`` argv) and allowlisted in
  SKILL.md's Hard rules (same pin shape as
  test_pipeline_contract's stagnation-check allowlist test). Release-payload
  discovery is not re-tested here: the payload gate already runs in CI.
* R6 - allowlisted in SKILL.md's Hard rules (see R5 note above).
* R7 - both Phase 6 green lanes (exit 0 bullet, exit 4 fallback bullet) each
  consult the script and route its exit 2 to ci-red (structural, per bullet).

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
    cause = {"malformed-json": "json", "missing-key": "head",
             "unresolvable-base": "no-such-branch"}
    for label, res in cases.items():
        assert res.returncode == 1, (label, res.stdout, res.stderr)
        assert "verdict: ok" not in res.stdout, label
        # A deliberate diagnostic, not an uncaught exception: Phase 6 quotes
        # this stderr into a `blocked` event.
        assert "Traceback" not in res.stderr, (label, res.stderr)
        assert cause[label] in res.stderr.lower(), (label, res.stderr)


def test_workflow_without_jobs_block_contributes_no_jobs(tmp_path):
    repo = _make_repo(
        tmp_path, {},
        {".github/workflows/empty.yml": "name: Empty\non: push\n"},
    )
    res = _run(repo, [])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verdict: ok" in res.stdout


# --- R5: model-free, allowlisted, consulted on both green lanes -------------

SCRIPT_REF = "scripts/ci-promised-check.py"
# Modules that would make the script talk to a network or a model.
_FORBIDDEN_IMPORT_ROOTS = {
    "urllib", "urllib3", "http", "socket", "ssl", "ftplib", "smtplib",
    "xmlrpc", "requests", "httpx", "aiohttp", "anthropic", "openai",
}


def _bullets(block, indent):
    """Split ``block`` into the list items that start at exactly ``indent``."""
    items, cur = [], None
    pat = re.compile(r"^" + " " * indent + r"- ")
    for line in block.splitlines():
        if pat.match(line):
            cur = [line]
            items.append(cur)
        elif cur is not None and (line.startswith(" " * (indent + 1))
                                  or not line.strip()):
            cur.append(line)
        else:
            cur = None
    return ["\n".join(i) for i in items]


def _is_git_argv(call):
    """True when the call's first argument is a literal list/tuple led by "git"."""
    import ast
    if not call.args:
        return False
    first = call.args[0]
    return (isinstance(first, (ast.List, ast.Tuple)) and first.elts
            and isinstance(first.elts[0], ast.Constant)
            and first.elts[0].value == "git")


def test_script_is_model_free():
    import ast
    assert SCRIPT.is_file()
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    roots = set()
    spawns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)                 and isinstance(node.func.value, ast.Name):
            owner, attr = node.func.value.id, node.func.attr
            if owner == "os" and (attr in ("system", "popen")
                                  or attr.startswith(("exec", "spawn"))):
                roots.add("os." + attr)
            elif owner == "subprocess" and not _is_git_argv(node):
                spawns.append(f"subprocess.{attr} at line {node.lineno}")
    bad = roots & _FORBIDDEN_IMPORT_ROOTS | {r for r in roots if r.startswith("os.")}
    assert not bad, f"ci-promised-check.py must be offline and model-free: {bad}"
    assert not spawns, ("every subprocess call must be a literal git argv list: "
                        f"{spawns}")


def test_script_is_allowlisted_in_the_hard_rules_delegation_bullet():
    text = SKILL.read_text(encoding="utf-8")
    hard = text[text.index("\n## Hard rules"):]
    bullets = _bullets(hard, 0)
    delegate = [b for b in bullets if b.startswith("- **Delegate everything.**")]
    assert len(delegate) == 1, "Hard rules must have one Delegate bullet"
    assert SCRIPT_REF in delegate[0]


def _phase6_step2_bullets():
    text = SKILL.read_text(encoding="utf-8")
    phase = text[text.index("\n## Phase 6"):]
    nxt = phase.find("\n## ", 1)
    if nxt != -1:
        phase = phase[:nxt]
    start = phase.index("\n2. Wait ")
    end = phase.index("\n3. ", start)
    return _bullets(phase[start:end], 3)


@pytest.mark.parametrize("lane", ["`0`", "`4`"], ids=["exit-0", "exit-4"])
def test_each_green_lane_consults_the_script_and_routes_gap_to_ci_red(lane):
    bullets = [b for b in _phase6_step2_bullets()
               if b.startswith("   - " + lane)]
    assert len(bullets) == 1, f"expected one exit-{lane} bullet"
    bullet = bullets[0]
    assert SCRIPT_REF in bullet
    assert "`2`" in bullet and "ci-red" in bullet
