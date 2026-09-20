"""
Package 120: Phase 6's CI wait must reach a verdict on Windows / Git Bash,
where the bare name `project-issues` resolves to an unexecutable Linux ELF
that sits beside `project-issues.exe` (rc=126).

These tests extract the single `wait-pipeline` Bash command SKILL.md
prescribes for Phase 6 and EXECUTE it under real bash with a PATH holding
  - an extensionless `project-issues` of non-executable bytes (the ELF), and
  - a working `project-issues.exe` stub (echo / false),
so what is verified is what the command does, not what its text contains.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
import sys

import pytest

from tests.test_ci_gate_wait import _BASH_CALL, _section, _skill
from tests.test_release_scripts import BASH, REPO_ROOT, _require_tool

PROJECT_ID = "acme/widgets"
HEAD_SHA = "abc1234def"


def _documented_command() -> str:
    phase6 = _section(_skill(), "Phase 6")
    calls = [c[0] for c in _BASH_CALL.findall(phase6) if "wait-pipeline" in c[0]]
    assert len(calls) == 1, f"Phase 6 must prescribe exactly one wait-pipeline call; found {len(calls)}"
    return calls[0].replace("<project_id>", PROJECT_ID).replace("<head>", HEAD_SHA)


def _bash_out(*args: str, env: dict | None = None) -> str:
    r = subprocess.run([BASH, "--noprofile", "--norc", *args], capture_output=True, text=True, env=env)
    return r.stdout.strip()


def _coreutil(name: str) -> pathlib.Path:
    p = _bash_out("-c", f"type -P {name}")
    assert p, f"coreutils {name} not found under bash"
    if sys.platform == "win32":
        p = _bash_out("-c", f'cygpath -m "{p}"')
    return pathlib.Path(p)


def _base_env(stubdir: pathlib.Path) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = REPO_ROOT.as_posix()
    parts = [str(stubdir)]
    if sys.platform == "win32":
        parts.append(str(pathlib.Path(BASH).parent.parent / "usr" / "bin"))
        parts.append(str(pathlib.Path(BASH).parent))
    parts.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(parts)
    return env


def _run(cmd: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)


def _make_elf_stub(stubdir: pathlib.Path) -> None:
    f = stubdir / "project-issues"
    f.write_bytes(b"\x7fELF" + b"\x00garbage-not-executable" * 8)
    f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_exe_stub(stubdir: pathlib.Path, tool: str, env: dict) -> None:
    exe = stubdir / "project-issues.exe"
    shutil.copy(_coreutil(tool), exe)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)


def _make_exe_script_stub(stubdir: pathlib.Path, body: str) -> None:
    exe = stubdir / "project-issues.exe"
    exe.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)


def _selfcheck(stubdir: pathlib.Path, env: dict, want_rc: int, want_out: str | None) -> str | None:
    """Return None when the fixture behaves, else a description of what is wrong."""
    r = _run([BASH, "--noprofile", "--norc", "-c", f'"{(stubdir / "project-issues").as_posix()}" x'], env)
    if r.returncode not in (126, 127):
        return f"fixture broken: ELF stub exits {r.returncode}, expected 126/127"
    r = _run([BASH, "--noprofile", "--norc", "-c", f'"{(stubdir / "project-issues.exe").as_posix()}" wait-pipeline --x'], env)
    if r.returncode != want_rc or (want_out is not None and want_out not in r.stdout):
        return f"fixture broken: .exe stub rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    return None


def _build_fixture(tmp_path: pathlib.Path, tool: str, want_rc: int, want_out: str | None) -> dict:
    stubdir = tmp_path / "stubs"
    stubdir.mkdir()
    env = _base_env(stubdir)
    _make_elf_stub(stubdir)
    _make_exe_stub(stubdir, tool, env)
    problem = _selfcheck(stubdir, env, want_rc, want_out)
    if problem:
        (stubdir / "project-issues.exe").unlink()
        body = 'echo "$@"' if tool == "echo" else "exit 1"
        _make_exe_script_stub(stubdir, body)
        problem = _selfcheck(stubdir, env, want_rc, want_out)
    assert problem is None, problem
    return env


def _run_documented(env: dict) -> subprocess.CompletedProcess:
    return _run([BASH, "--noprofile", "--norc", "-c", _documented_command()], env)


def test_documented_wait_uses_the_executable_binary(tmp_path):
    _require_tool(BASH, "bash")
    env = _build_fixture(tmp_path, "echo", 0, "wait-pipeline")
    r = _run_documented(env)
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    assert f"wait-pipeline --project {PROJECT_ID} --sha {HEAD_SHA} --timeout 540" in r.stdout


def test_documented_wait_passes_a_failing_exit_through(tmp_path):
    _require_tool(BASH, "bash")
    env = _build_fixture(tmp_path, "false", 1, None)
    r = _run_documented(env)
    assert r.returncode == 1, f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"


def test_no_usable_cli_exits_four_and_reports_candidates(tmp_path):
    _require_tool(BASH, "bash")
    stubdir = tmp_path / "stubs"
    stubdir.mkdir()
    env = _base_env(stubdir)
    _make_elf_stub(stubdir)
    problem = _selfcheck_elf_only(stubdir, env)
    assert problem is None, problem
    r = _run_documented(env)
    assert r.returncode not in (126, 127), f"wrapper leaked rc={r.returncode}: {r.stderr!r}"
    assert r.returncode == 4, f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "project-issues.exe" in r.stderr and "project-issues" in r.stderr
    assert "rc=126" in r.stderr or "rc=127" in r.stderr


def _selfcheck_elf_only(stubdir: pathlib.Path, env: dict) -> str | None:
    r = _run([BASH, "--noprofile", "--norc", "-c", f'"{(stubdir / "project-issues").as_posix()}" x'], env)
    if r.returncode not in (126, 127):
        return f"fixture broken: ELF stub exits {r.returncode}, expected 126/127"
    return None
