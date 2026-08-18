"""
Regression tests for ticket #84: the pytest suite had no per-test timeout
configured, so a wedged helper subprocess (git/node) could hang an entire
run indefinitely -- the failure mode that stalls the autonomous fleet
agents forever (sibling ticket #83).

Fix: declare `pytest-timeout` as a test dependency and set
`timeout = 60` / `timeout_method = "thread"` under
`[tool.pytest.ini_options]` in pyproject.toml (thread, not signal --
cross-platform, this repo is developed on Windows where signal-based
timeouts don't work).

Behavioural requirements (see the approved plan for ticket #84):
  BR1 - the timeout configuration is present and live in the running
        session: request.config.getini("timeout") / ("timeout_method")
        resolve to 60 / "thread", proving the plugin is actually
        registered and actually configured (not merely installed).
  BR2 - a test that blocks indefinitely is terminated within the
        configured timeout instead of hanging the run.
  AC#3 - the real suite still passes with the timeout in place (verified
        separately by running the full suite, not by a test in this
        file).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_pyproject_dict() -> dict:
    """Parse pyproject.toml, preferring stdlib tomllib (py >= 3.11)."""
    if sys.version_info >= (3, 11):
        import tomllib

        with open(PYPROJECT, "rb") as f:
            return tomllib.load(f)
    raise RuntimeError("tomllib unavailable and no fallback parser wired here")


def _pytest_ini_options_text() -> str:
    """Return the raw [tool.pytest.ini_options] table text as a fallback
    for parsing on interpreters without tomllib (py < 3.11)."""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(
        r"\[tool\.pytest\.ini_options\](.*?)(?:\n\[|\Z)", text, re.DOTALL
    )
    assert match, "pyproject.toml has no [tool.pytest.ini_options] table"
    return match.group(1)


def _extract_timeout_method(block: str) -> str | None:
    """Extract the `timeout_method` value from a TOML/ini text block.

    Accepts both double- and single-quoted string values -- TOML permits
    either quote style, and pyproject.toml is free to use `'thread'` just
    as validly as `"thread"`. Returns None when the key isn't present.
    """
    match = re.search(r"""timeout_method\s*=\s*["']([^"']+)["']""", block)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# BR1 - the timeout configuration is present and live in the running session
# ---------------------------------------------------------------------------


def test_session_has_sixty_second_thread_timeout(request):
    """Driving test for BR1.

    request.config.getini("timeout") raises ValueError when pytest-timeout
    is not installed/registered (the ini key is unknown to pytest), so this
    assertion is a live proof that the plugin is both installed AND
    configured for THIS session -- not just declared as a dependency.
    pytest-timeout registers "timeout" with type="float" (so getini returns
    a float, defaulting to 0.0 when unconfigured -- a genuinely missing
    configuration, not an error) and registers "timeout_method" as a plain
    untyped string ini, so float() around raw_timeout is defensive/no-op
    normalization rather than a required string->float conversion.
    """
    try:
        raw_timeout = request.config.getini("timeout")
        raw_method = request.config.getini("timeout_method")
    except ValueError:
        pytest.fail(
            "pytest-timeout is not installed -- the 'timeout' ini option is "
            "unregistered, so timeout = 60 in pyproject.toml is a silent "
            "no-op and nothing bounds a hanging test"
        )

    assert float(raw_timeout) == 60.0, (
        f"expected the configured per-test timeout to be 60 seconds, got "
        f"{raw_timeout!r}"
    )
    assert raw_method.strip() == "thread", (
        f"expected timeout_method = 'thread' (signal-based timeouts don't "
        f"work on Windows), got {raw_method!r}"
    )


def test_pyproject_declares_pytest_timeout_dependency():
    """Additional coverage for BR1: pytest-timeout must be a *declared*
    test dependency, not merely ambient-installed in the interpreter
    running this test -- otherwise a fresh clone/venv would silently lose
    timeout enforcement while this repo's own getini() check kept passing
    on a machine that happens to have it globally installed.

    Scoped to interpreters with stdlib tomllib (py >= 3.11): the ambient
    interpreter this repo runs on is 3.14, and a regex-based TOML fallback
    for older interpreters proved fragile (round-2 reviewer findings --
    unanchored/non-greedy matching against the *whole*
    optional-dependencies table produced both false positives and false
    negatives). Skipping on < 3.11 rather than maintaining a hand-rolled
    TOML parser in a test file is the deliberate, reviewed tradeoff; this
    check is additional coverage, not a driving test."""
    if sys.version_info < (3, 11):
        pytest.skip(
            "tomllib is unavailable before Python 3.11; the dependency "
            "declaration is checked on 3.11+"
        )
    data = _load_pyproject_dict()
    test_deps = data["project"]["optional-dependencies"]["test"]
    assert any(dep.startswith("pytest-timeout") for dep in test_deps), (
        f"'pytest-timeout' is not declared in "
        f"[project.optional-dependencies].test: {test_deps!r}"
    )


def test_timeout_method_is_thread_not_signal():
    """Additional coverage for BR1: pin the method to 'thread' explicitly,
    with a message explaining why 'signal' is wrong for this repo (it does
    not work on Windows, where this repo is developed)."""
    block = _pytest_ini_options_text()
    method = _extract_timeout_method(block)
    assert method is not None, (
        "no timeout_method key found in [tool.pytest.ini_options]"
    )
    assert method == "thread", (
        "timeout_method must be 'thread', not 'signal' -- signal-based "
        "timeouts do not work on Windows"
    )


def test_extract_timeout_method_accepts_single_quoted_value():
    """Regression test for a reviewer blocking finding on this file:
    _extract_timeout_method must accept single-quoted TOML string values,
    not just double-quoted ones -- TOML permits either quote style, so
    `timeout_method = 'thread'` is just as valid as `timeout_method =
    "thread"`.

    Driving test: feeds the helper a single-quoted snippet directly. Against
    the original double-quote-only regex this returns None (no match)
    instead of "thread"."""
    assert _extract_timeout_method("timeout_method = 'thread'") == "thread", (
        "expected a single-quoted timeout_method value to be parsed just "
        "like a double-quoted one"
    )


def test_global_timeout_value_is_sixty():
    """Additional coverage for BR1: pin the exact configured value. Raising
    this global bound (rather than adding a targeted
    @pytest.mark.timeout(N) override) is a deliberate, reviewed act -- see
    tests/test_release_script_packaging.py's
    test_allowed_unshipped_is_empty_at_landing for the same convention."""
    block = _pytest_ini_options_text()
    match = re.search(r"timeout\s*=\s*(\d+)", block)
    assert match, "no timeout key found in [tool.pytest.ini_options]"
    assert int(match.group(1)) == 60, (
        f"expected the global per-test timeout to be 60, got "
        f"{match.group(1)}. If a specific test legitimately needs longer, "
        f"add a targeted @pytest.mark.timeout(N) to that test instead of "
        f"raising the global value."
    )


# ---------------------------------------------------------------------------
# BR2 - a test that blocks indefinitely is terminated within the timeout
# ---------------------------------------------------------------------------


def _sandbox_ini_lines() -> list[str]:
    """Derive the sandbox pytest.ini's timeout lines from THIS repo's own
    [tool.pytest.ini_options] table, scaling the numeric value down purely
    for test speed. Deliberately does NOT hardcode a timeout value into the
    sandbox: hardcoding would make the driving test pass even before the
    real fix landed (a fabricated RED), because the ambient interpreter
    already has pytest-timeout installed.

    Returns an empty list when the repo config carries no timeout keys yet
    (pre-fix state) -- the sandbox then inherits NO timeout at all, which is
    exactly the behaviour under test.
    """
    block = _pytest_ini_options_text()
    lines = []
    timeout_match = re.search(r"timeout\s*=\s*(\d+)", block)
    if timeout_match:
        # Scale down for speed; keep well under the outer subprocess bound.
        lines.append("timeout = 2")
    method = _extract_timeout_method(block)
    if method is not None:
        lines.append(f"timeout_method = {method}")
    return lines


def _write_sandbox_pytest_ini(tmp_path: Path) -> None:
    lines = _sandbox_ini_lines()
    content = "[pytest]\n" + "".join(f"{line}\n" for line in lines)
    (tmp_path / "pytest.ini").write_text(content, encoding="utf-8")


def test_blocking_test_is_terminated_by_timeout(tmp_path):
    """Driving test for BR2.

    Writes a sandbox pytest.ini derived from this repo's own ini table
    (see _sandbox_ini_lines) plus a test that blocks forever, then runs a
    nested pytest against it under an outer subprocess timeout bound.

    Pre-fix (RED): the repo config has no timeout key -> the sandbox
    inherits none -> nothing bounds the sleep -> the outer 30s bound trips
    -> pytest.fail with a message explaining the timeout is not enforced.

    Post-fix (GREEN): the repo config carries timeout = 60 (scaled to 2 in
    the sandbox) -> the inner pytest run dies in ~2-3s with a Timeout
    banner and non-zero exit code.
    """
    _write_sandbox_pytest_ini(tmp_path)
    (tmp_path / "test_hang.py").write_text(
        "import time\n\n\ndef test_hangs_forever():\n    time.sleep(300)\n",
        encoding="utf-8",
    )

    start = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "test_hang.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            "the blocking test was never terminated -- the per-test "
            "timeout is not being enforced (outer 30s subprocess bound "
            "tripped instead)"
        )
    elapsed = time.monotonic() - start

    assert result.returncode != 0, (
        "expected the inner pytest run to fail (timeout-killed test), but "
        f"it exited 0. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined_output = result.stdout + result.stderr
    assert "Timeout" in combined_output, (
        "expected pytest-timeout's '+++ Timeout +++' banner in the inner "
        f"run's output, got stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert elapsed < 20, (
        f"expected the timeout-bounded inner run to finish quickly, took "
        f"{elapsed:.1f}s"
    )


def test_fast_test_is_unaffected_by_timeout(tmp_path):
    """Additional coverage for BR2: a normal fast test is unaffected by the
    configured timeout -- collateral-damage guard, not a driver, and may
    legitimately already pass."""
    _write_sandbox_pytest_ini(tmp_path)
    (tmp_path / "test_fast.py").write_text(
        "def test_is_fast():\n    assert True\n", encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "test_fast.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"expected the fast test to pass, got returncode={result.returncode} "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined_output = result.stdout + result.stderr
    assert "Timeout" not in combined_output, (
        "a fast test must not trigger the timeout banner"
    )


def test_marker_override_extends_the_timeout(tmp_path):
    """Additional coverage for BR2: pins the documented escape hatch --
    @pytest.mark.timeout(N) on an individual test overrides a short ini
    timeout, letting a legitimately slow test opt out without raising the
    global bound. Uses a self-contained ini timeout = 1 (not derived from
    the repo config) specifically to prove the marker overrides an even
    shorter bound than the repo's own."""
    (tmp_path / "pytest.ini").write_text("[pytest]\ntimeout = 1\n", encoding="utf-8")
    (tmp_path / "test_marker.py").write_text(
        "import time\nimport pytest\n\n\n"
        "@pytest.mark.timeout(10)\n"
        "def test_slow_but_marked():\n"
        "    time.sleep(3)\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "test_marker.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"expected the marker-overridden test to pass despite exceeding "
        f"the ini timeout, got returncode={result.returncode} "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
