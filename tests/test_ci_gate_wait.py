"""
Ticket #118: Phase 6 of process-ticket waits for CI with one blocking
foreground `project-issues wait-pipeline` call instead of a `sleep` ladder.

Only what a machine reads is tested here:
  R1 - the prescribed wait call is one hooks/check-no-background.mjs permits
       (and its detached variants it refuses), and its tool `timeout:` outlives
       the CLI's own `--timeout`.
  R2 - no `sleep` / `Start-Sleep` / `Monitor` token is left in the CI gate or
       in the two rules that used to prescribe the sleep poll.
Routing prose (exit codes, no-verdict policy) is instructions to the executing
model and is deliberately not pattern-matched.
"""

from __future__ import annotations

import pathlib
import re

from tests.test_no_background_rule import _pipeline_cwd, _run_pre, _assert_allowed, _assert_refused

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

_BASH_CALL = re.compile(r'Bash\(\s*"([^"]*)"(?:\s*,\s*timeout:\s*(\d+))?\s*\)')


def _section(text: str, heading: str, level: str = "## ") -> str:
    m = re.search(
        r"^" + re.escape(level + heading) + r".*?$(.*?)(?=^" + re.escape(level) + r"\S|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"heading {level}{heading!r} not found"
    return m.group(1)


def _skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _turn_end_rule_1() -> str:
    m = re.search(r"^1\. .*?(?=^2\. )", _section(_skill(), "Turn-end discipline"), re.MULTILINE | re.DOTALL)
    assert m, "Turn-end rule 1 not found"
    return m.group(0)


def _hard_rules_bash_allowance() -> str:
    items = [x for x in re.split(r"(?m)^(?=- )", _section(_skill(), "Hard rules")) if "`Bash`" in x]
    assert len(items) == 1, "exactly one Hard-rules item must carry the `Bash` allowance"
    return items[0]


def test_phase6_prescribes_one_wait_pipeline_call_the_hook_permits(tmp_path):
    phase6 = _section(_skill(), "Phase 6")
    calls = [c for c in _BASH_CALL.findall(phase6) if "wait-pipeline" in c[0]]
    assert len(calls) == 1, f"Phase 6 must prescribe exactly one wait-pipeline Bash call; found {len(calls)}"
    command, timeout_ms = calls[0]
    assert timeout_ms, "the wait-pipeline call must carry an explicit tool timeout"
    m = re.search(r"--timeout\s+(\d+)\b", command)
    assert m, "the wait-pipeline call must pass --timeout <seconds>"
    assert int(m.group(1)) * 1000 < int(timeout_ms) <= 600000, (
        "tool timeout must outlive the CLI's --timeout and fit the 600000 ms Bash ceiling"
    )
    cwd = _pipeline_cwd(tmp_path)
    _assert_allowed(_run_pre("Bash", {"command": command, "timeout": int(timeout_ms)}, cwd=cwd))
    for detached in (f"nohup {command}", f"{command} &"):
        _assert_refused(_run_pre("Bash", {"command": detached}, cwd=cwd))


def test_ci_gate_and_its_rules_carry_no_sleep_or_monitor():
    skill = _skill()
    sleep = re.compile(r"\bsleep\b|Start-Sleep", re.I)
    monitor = re.compile(r"\bMonitor\b", re.I)
    # Turn-end rule 1 keeps naming `Monitor` - as a forbidden shape, which
    # test_no_background_rule.py requires - so only `sleep` is checked there.
    spans = {
        "Phase 6": (_section(skill, "Phase 6"), (sleep, monitor)),
        "Turn-end rule 1": (_turn_end_rule_1(), (sleep,)),
        "Hard-rules Bash allowance": (_hard_rules_bash_allowance(), (sleep, monitor)),
    }
    offenders = {
        name: sorted({h for rx in rxs for h in rx.findall(t)})
        for name, (t, rxs) in spans.items()
        if any(rx.search(t) for rx in rxs)
    }
    assert not offenders, f"sleep/Start-Sleep/Monitor must not appear in: {offenders}"
