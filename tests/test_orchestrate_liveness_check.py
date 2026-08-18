"""
Regression tests for ticket #83: `orchestrate-tickets`' B6 status-check-ping
bound must become a defined, bounded liveness/progress check instead of "no
wall-clock timeout, no retry count", and the orchestrator's own long waits
must dog-food the same nohup+Monitor pattern this ticket mandates for
sub-agents (see test_agent_background_wait.py).

Root cause: the postmortem found that B6's coherent-reply outcome bought a
wave member unbounded silence with no wall clock, so two idle agents could
wait on each other indefinitely with no automatic recovery — the user had to
intervene 12 times over a 9-hour run. This is a liveness/progress check, not
a deadline: it must not weaken "never merge on self-report alone", the five
Conservative non-merge disqualifiers, or the `final: true` confirmed-done
keying.

Fix: `skills/orchestrate-tickets/SKILL.md` Phase C step 2 and the Hard Rules
B6 bullet both replace the old "no wall-clock timeout, no retry count"
wording with an explicit bounded ~15-minute wait, three named liveness
probes (process-alive by command line/worktree path, CPU-time delta, `git
diff --stat` growth), a single alive-vs-wedged verdict, and — on wedged — a
kill (via the existing B2 sweep) followed by fall-through to the unchanged
Conservative non-merge rule, with no automatic re-dispatch. The bounded wait
itself is implemented via the same `nohup … &` + in-turn `Monitor` pattern
mandated for sub-agents (never a foreground sleep, which would hit the same
~10-minute tool cliff this ticket fixes), and Phase C step 5's integration
gate (a full-suite run) uses the same backgrounded form after its existing
`Set-Location`/`cd` first statement. `AGENTS.md`'s B6 section and Long-lived
process guardrail section are updated to match.

Red -> green: these tests fail against the pre-#83 SKILL.md/AGENTS.md (old
"no wall-clock timeout" phrasing, no nohup/Monitor anywhere in
orchestrate-tickets/SKILL.md) and pass once the bounded liveness check, its
probes, the kill-then-disqualify/no-re-dispatch outcome, and the dog-food
wait pattern are documented in both files, with all preserved guarantees
(five disqualifiers, `final: true`, self-report-alone ban, marker filename)
still intact.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _extract_phase_c_step2(body: str) -> str:
    m = re.search(
        r"B6 status-check ping.*?(?=\n\s*3\. \*\*Checkout the integration branch)",
        body,
        re.DOTALL,
    )
    assert m, "SKILL.md must contain Phase C step 2's B6 ping sub-step"
    return m.group(0)


def _extract_phase_c_step5(body: str) -> str:
    m = re.search(
        r"5\. \*\*Integration gate.*?(?=\n## Phase D)", body, re.DOTALL
    )
    assert m, "SKILL.md must contain Phase C step 5 (integration gate)"
    return m.group(0)


def _extract_hard_rules_b6(body: str) -> str:
    m = re.search(
        r"\*\*Never merge on self-report alone \(B6\)\.\*\*.*?(?=\n- \*\*Backlog release gate)",
        body,
        re.DOTALL,
    )
    assert m, "SKILL.md must contain the Hard Rules B6 bullet"
    return m.group(0)


# ---------------------------------------------------------------------------
# BR5 — bounded liveness check replaces "no wall-clock timeout"
# ---------------------------------------------------------------------------


def test_b6_ping_bound_is_a_bounded_liveness_check():
    body = _read(ORCHESTRATE_MD)
    step2 = _normalize(_extract_phase_c_step2(body))
    hard_rules = _normalize(_extract_hard_rules_b6(body))

    for section, label in ((step2, "Phase C step 2"), (hard_rules, "Hard Rules B6")):
        assert "15" in section and (
            "minute" in section.lower()
        ), f"{label} must state the bounded ~15-minute wait"

        # Three named probes.
        assert (
            "command line" in section.lower() or "worktree path" in section.lower()
        ), f"{label} must name the process-alive-by-command-line/worktree-path probe"
        assert "cpu" in section.lower(), f"{label} must name the CPU-time-delta probe"
        assert "diff --stat" in section, (
            f"{label} must name the git diff --stat growth probe"
        )

        # Wedged outcome: kill then disqualify, no auto re-dispatch.
        assert "kill" in section.lower(), f"{label} must state the wedged member is killed"
        assert "re-dispatch" in section.lower(), (
            f"{label} must explicitly rule out automatic re-dispatch"
        )
        assert "conservative non-merge" in section.lower() or "non-merge rule" in section.lower(), (
            f"{label} must route the wedged outcome to the Conservative non-merge rule"
        )

    # Negative guard: the old unbounded phrasing must be fully gone from the file.
    full_norm = _normalize(body)
    assert "no wall-clock timeout" not in full_norm.lower()
    assert "no timer, no retry" not in full_norm.lower()


def test_git_diff_stat_probe_is_worktree_pinned_per_ticket_66():
    """The new `git diff --stat` probe must be written `git -C <worktree_path>
    diff --stat` per the #66 cwd-independence invariant, or it would trip the
    existing negative guard in test_orchestrate_cwd_independent_git.py, which
    flags a bare `git diff` anywhere in the file."""
    body = _read(ORCHESTRATE_MD)
    assert "git -C <worktree_path> diff --stat" in body or re.search(
        r"git -C <worktree_path> diff --stat", body
    ), "the git diff --stat liveness probe must be pinned via -C <worktree_path>"


def test_preserved_guarantees_survive_the_b6_rewrite():
    body = _read(ORCHESTRATE_MD)
    norm = _normalize(body)

    assert "never merge on self-report alone" in norm.lower()

    # Five disqualifiers, still exactly five, still present verbatim in substance.
    disqualifiers = [
        "HEAD not ahead of the branch point",
        "marker file missing or unreadable",
        "not matching this member's actual ticket number",
        "verdict` is not `APPROVE`",
        "test` is not `PASS`",
    ]
    for d in disqualifiers:
        assert d in norm, f"Conservative non-merge rule must still name: {d}"

    assert "final: true" in body or "`final: true`" in body
    assert ".process-ticket-result.json" in body


# ---------------------------------------------------------------------------
# BR6 — orchestrator's own long waits dog-food nohup + Monitor
# ---------------------------------------------------------------------------


def test_orchestrator_long_waits_use_nohup_monitor_not_foreground_sleep():
    body = _read(ORCHESTRATE_MD)
    norm = _normalize(body)

    assert "nohup" in norm and "Monitor" in norm, (
        "SKILL.md must document the bounded wait using nohup + Monitor"
    )
    assert "foreground" in norm.lower() and (
        "sleep" in norm.lower() or "start-sleep" in norm.lower()
    ), "SKILL.md must explicitly forbid a foreground sleep/Start-Sleep wait"
    assert "10-minute" in norm or "~10-minute" in norm, (
        "SKILL.md must explain the foreground-sleep prohibition via the "
        "~10-minute tool cliff"
    )

    step5 = _normalize(_extract_phase_c_step5(body))
    assert "nohup" in step5 and "Monitor" in step5, (
        "Phase C step 5's integration gate must use the backgrounded "
        "nohup + Monitor pattern"
    )
    assert "Set-Location <repo_root>" in step5 or "cd <repo_root>" in step5, (
        "Phase C step 5 must keep its Set-Location/cd <repo_root> first "
        "statement"
    )


def test_integration_gate_ordering_and_no_auto_revert_unchanged():
    body = _read(ORCHESTRATE_MD)
    step5 = _normalize(_extract_phase_c_step5(body))
    assert "push origin" in step5 and "before the next wave" in step5.lower()
    assert "no automatic revert" in step5.lower() or "no auto" in step5.lower()


# ---------------------------------------------------------------------------
# BR7 — AGENTS.md documentation stays consistent
# ---------------------------------------------------------------------------


def test_agents_md_documents_bounded_liveness_check():
    norm = _normalize(_read(AGENTS_MD))

    assert "no wall-clock timeout" not in norm.lower()
    assert "15" in norm and "minute" in norm.lower()
    assert "cpu" in norm.lower()
    assert "diff --stat" in norm
    assert "kill" in norm.lower()
    assert "re-dispatch" in norm.lower()
    assert "nohup" in norm and "Monitor" in norm


def test_agents_md_long_lived_process_section_covers_never_end_turn_boundary():
    body = _read(AGENTS_MD)
    m = re.search(
        r"## Long-lived process guardrail.*?(?=\n## )", body, re.DOTALL
    )
    assert m, "AGENTS.md must contain the Long-lived process guardrail section"
    section = _normalize(m.group(0))

    assert "never end" in section.lower() and "turn" in section.lower(), (
        "the guardrail section must cover the never-end-turn-on-a-"
        "backgrounded-command rule as its second cross-file branch"
    )
    assert "full-suite" in section.lower() and "foreground" in section.lower(), (
        "the guardrail section must record the full-suite-always / "
        "targeted-may-be-foreground boundary as an invariant"
    )
