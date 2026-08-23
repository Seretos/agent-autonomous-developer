"""
Regression test: this repo's own test suite (tests/, currently 100+ tests
pinning agent/hook/script behaviour) was never wired into CI. `.github/
workflows/lint.yml` only validated plugin.json and skill/agent frontmatter;
`.github/workflows/release.yml` only runs on manual dispatch. A PR could
merge with a failing or entirely broken test suite and CI would stay green
throughout — directly contradicting this repo's own "CI is the verdict"
principle (AGENTS.md), just applied to the plugin's own tests instead of a
target project's.

Fix: add a `test` job to `.github/workflows/lint.yml` that installs the
`test` extra and runs `python -m pytest`. This test pins that the job
exists and actually invokes pytest, on both push and pull_request triggers
(the same triggers the `validate` job already runs under) — so a future
edit that removes or defangs the job is itself caught by this test.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
LINT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lint.yml"


def _load_workflow() -> dict:
    text = LINT_WORKFLOW.read_text(encoding="utf-8")
    # YAML parses the bare "on:" key as the boolean True, not the string
    # "on" — irrelevant to this test, but noted so a future reader isn't
    # surprised by data["on"] failing to look up cleanly.
    return yaml.safe_load(text)


def test_lint_workflow_has_a_test_job():
    data = _load_workflow()
    jobs = data.get("jobs", {})
    assert "test" in jobs, (
        f"{LINT_WORKFLOW} must define a 'test' job that runs the repo's "
        "own pytest suite — currently missing, so tests/ is never "
        "executed in CI."
    )


def test_test_job_runs_on_push_and_pull_request():
    data = _load_workflow()
    triggers = data.get(True, data.get("on", {}))
    assert "push" in triggers, f"{LINT_WORKFLOW} must trigger on push."
    assert "pull_request" in triggers, (
        f"{LINT_WORKFLOW} must trigger on pull_request."
    )


def test_test_job_actually_invokes_pytest():
    data = _load_workflow()
    test_job = data["jobs"]["test"]
    steps = test_job.get("steps", [])
    run_commands = " ".join(step.get("run", "") for step in steps)
    assert "pytest" in run_commands, (
        f"{LINT_WORKFLOW}'s 'test' job must actually invoke pytest — no "
        "'pytest' found in any step's run command."
    )
    assert "install" in run_commands.lower(), (
        f"{LINT_WORKFLOW}'s 'test' job must install the project's test "
        "dependencies before running pytest."
    )


def test_test_job_uses_setup_python():
    data = _load_workflow()
    test_job = data["jobs"]["test"]
    steps = test_job.get("steps", [])
    uses = [step.get("uses", "") for step in steps]
    assert any("setup-python" in u for u in uses), (
        f"{LINT_WORKFLOW}'s 'test' job must set up a Python interpreter "
        "via actions/setup-python before installing/running pytest."
    )
