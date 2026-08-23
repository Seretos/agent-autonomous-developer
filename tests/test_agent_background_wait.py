"""
Regression tests for ticket #83: a `developer`/`reviewer` sub-agent must
never end its turn while a command it backgrounded is still running.

Root cause (from a 9-hour, 12-manual-intervention `orchestrate-tickets`
fleet-run postmortem): a `task-notification` event for a backgrounded Bash
command is delivered only to the main/orchestrator session, never to the
sub-agent that actually started the background task. A sub-agent that tries
to "wait" by ending its turn (or by issuing a no-op yield like `true`,
`exit 0`, or `echo waiting`) is not suspended — it is *terminated* — leaving
the parent believing the sub-agent is still working when it no longer
exists. Two idle agents waiting on each other this way can stall a run
indefinitely with no automatic recovery.

Fix: `agents/developer.md` and `agents/reviewer.md` each gain a Hard Rule
forbidding ending a turn on a self-backgrounded command, naming the two
sanctioned alternatives — an in-turn `Monitor` wait, or an explicit
blocked/in-progress status report — and naming `true`/`exit 0`/
`echo waiting` (plus `sleep` as a turn filler) as a forbidden anti-pattern.
`agents/developer.md`'s "Run the suite" step documents `nohup … > <log>
2>&1 &` + an in-turn `Monitor` wait as the **always** pattern for full-suite
runs (never gated on an expected-duration estimate), with an explicit
carve-out permitting plain foreground calls for targeted red→green-loop
runs. `skills/process-ticket/SKILL.md` is updated to treat a blocked/
in-progress report as a legitimate return that must be surfaced and must
never be treated as a completed phase.

Red -> green: these tests fail against the pre-#83 agent/skill files (no
such rule exists anywhere) and pass once the rule, the anti-pattern list,
the nohup+Monitor pattern, and the process-ticket blocked/in-progress branch
are all documented.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
REVIEWER_MD = REPO_ROOT / "agents" / "reviewer.md"
PROCESS_TICKET_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

AGENT_FILES = [DEVELOPER_MD, REVIEWER_MD]


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    """Collapse all whitespace runs (including markdown hard-wraps) to a
    single space so substring checks are tolerant of line-wrapping."""
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# BR1 — both agents forbid ending a turn on a backgrounded command
# ---------------------------------------------------------------------------


def test_both_agents_forbid_ending_turn_on_backgrounded_command():
    for path in AGENT_FILES:
        norm = _normalize(_read(path))
        assert "never end" in norm.lower() and "turn" in norm.lower(), (
            f"{path} must forbid ending a turn while a backgrounded command "
            "is still running"
        )
        assert "task-notification" in norm, (
            f"{path} must explain that task-notification events for a "
            "backgrounded command go only to the main/orchestrator session"
        )
        # Sanctioned alternative (a): in-turn Monitor wait.
        assert "Monitor" in norm, (
            f"{path} must name the in-turn Monitor wait as a sanctioned way "
            "to wait on a backgrounded command"
        )
        # Sanctioned alternative (b): explicit blocked/in-progress report.
        assert "blocked" in norm.lower() and "in-progress" in norm.lower(), (
            f"{path} must name an explicit blocked/in-progress status "
            "report as a sanctioned alternative to waiting in-turn"
        )


def test_reviewer_hard_rules_carry_the_rule_not_just_developer():
    """The plan requires the rule 'verbatim in substance' in the reviewer's
    own Hard rules section, not merely inherited from developer.md."""
    body = _read(REVIEWER_MD)
    m = re.search(r"## Hard rules.*", body, re.DOTALL | re.IGNORECASE)
    assert m, "reviewer.md must contain a '## Hard rules' section"
    hard_rules = _normalize(m.group(0))
    assert "never end" in hard_rules.lower() and "turn" in hard_rules.lower()
    assert "Monitor" in hard_rules


def test_reviewer_codex_step_points_to_the_new_hard_rule():
    """Codex step 3 stays read-only/foreground but must point at the new
    Hard Rule in case that call is ever backgrounded."""
    norm = _normalize(_read(REVIEWER_MD))
    assert "read-only, foreground" in norm, (
        "reviewer.md's Codex step 3 must keep its read-only, foreground "
        "framing"
    )
    # A pointer from step 3 forward to the Hard Rule's Monitor requirement.
    idx = norm.find("Run the review via the bundled script")
    assert idx != -1, "reviewer.md must still contain Codex step 3"
    tail = norm[idx : idx + 1200]
    assert "backgrounded" in tail and "Monitor" in tail, (
        "Codex step 3 must cross-reference the Hard Rule's in-turn Monitor "
        "wait in case the call is ever backgrounded"
    )


# ---------------------------------------------------------------------------
# BR2 — no-op yield commands named explicitly as an anti-pattern
# ---------------------------------------------------------------------------


def test_noop_yield_commands_named_as_antipattern():
    for path in AGENT_FILES:
        norm = _normalize(_read(path))
        assert "anti-pattern" in norm.lower() or "antipattern" in norm.lower(), (
            f"{path} must explicitly label the no-op yields as an "
            "anti-pattern"
        )
        for literal in ("`true`", "`exit 0`", "`echo waiting`"):
            assert literal in norm, (
                f"{path} must name {literal} as a forbidden no-op yield"
            )
        assert "turn filler" in norm.lower() or "as a turn filler" in norm.lower(), (
            f"{path} must call out `sleep` used as a turn filler"
        )


def test_antipattern_text_does_not_contradict_bash_building_testing_rule():
    """Negative guard: developer.md:143's existing 'Bash is for building and
    testing' rule must survive the new anti-pattern bullet untouched."""
    norm = _normalize(_read(DEVELOPER_MD))
    assert "Bash is for building and testing" in norm


# ---------------------------------------------------------------------------
# BR3 — full-suite pattern is nohup + Monitor, always, with a targeted
# foreground carve-out
# ---------------------------------------------------------------------------


def test_run_suite_documents_nohup_plus_monitor_pattern():
    body = _read(DEVELOPER_MD)
    m = re.search(r"4\. \*\*Run the suite\.\*\*.*?(?=\n5\. )", body, re.DOTALL)
    assert m, "developer.md must contain a numbered 'Run the suite' step 4"
    step = _normalize(m.group(0))

    assert "nohup" in step and "Monitor" in step, (
        "step 4 must document the nohup + Monitor backgrounded pattern"
    )
    assert "2>&1 &" in step, "step 4 must show the detached-run redirection form"

    # Unconditional wording: no duration-estimate escape hatch.
    assert "regardless of how long" in step.lower(), (
        "step 4 must state the full-suite backgrounded rule applies "
        "regardless of expected duration"
    )

    # Targeted-run carve-out.
    assert "foreground" in step.lower() and (
        "targeted" in step.lower() or "red" in step.lower()
    ), "step 4 must explicitly permit foreground calls for targeted runs"


def test_run_suite_stays_stack_neutral_with_pytest_as_labelled_example():
    body = _read(DEVELOPER_MD)
    m = re.search(r"4\. \*\*Run the suite\.\*\*.*?(?=\n5\. )", body, re.DOTALL)
    assert m
    step = _normalize(m.group(0))

    for marker in ("pyproject.toml", "package.json", "go.mod", "Cargo.toml"):
        assert marker in step, f"step 4 must still enumerate {marker}"

    assert "--timeout" in step and "#84" in step, (
        "step 4 must frame the pytest --timeout flags as an example and "
        "cross-reference ticket #84"
    )


# ---------------------------------------------------------------------------
# BR4 — process-ticket handles a blocked/in-progress report
# ---------------------------------------------------------------------------


def test_process_ticket_handles_blocked_in_progress_report():
    norm = _normalize(_read(PROCESS_TICKET_MD))
    assert "blocked" in norm.lower() and "in-progress" in norm.lower(), (
        "process-ticket SKILL.md must document a blocked/in-progress "
        "return from the developer or reviewer"
    )
    assert "surface" in norm.lower(), (
        "process-ticket SKILL.md must say a blocked/in-progress report is "
        "surfaced to the user"
    )
    assert "not proceed to commit" in norm.lower() or (
        "never" in norm.lower() and "proceed to commit" in norm.lower()
    ), (
        "process-ticket SKILL.md must say a blocked/in-progress report is "
        "never treated as a completed phase and must not proceed to commit"
    )


# ---------------------------------------------------------------------------
# BR5 (ticket #88, reviewer fix round 2, finding 6) — recovered from the
# wholesale-deleted tests/test_orchestrate_liveness_check.py: AGENTS.md's
# cross-file "## Long-lived process guardrail" section must still cover the
# never-end-turn-on-a-backgrounded-command rule (BR1 above, restated
# cross-file) and the full-suite-always/targeted-may-be-foreground boundary.
# AGENTS.md itself calls this an invariant a later edit "must not quietly
# narrow" -- ticket #88 must not be the edit that silently drops its test
# coverage, even though #88's own changes don't touch this section's
# substance.
# ---------------------------------------------------------------------------


AGENTS_MD = REPO_ROOT / "AGENTS.md"


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
