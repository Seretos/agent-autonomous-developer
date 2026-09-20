"""
Ticket #112 -- a Codex-only blocking review round is not "progress" for the
review gate's round-cap purposes, and must not by itself buy a developer fix
round or drive the gate to its hard cap and a replan. The reviewer already
tags every Codex-sourced finding `"kind": "codex"` (agents/reviewer.md, "What
you return"); this plan reuses that token rather than adding a new one.

Two changes land in the implement phase (deliberately NOT made yet -- this is
the tests-only RED phase):

  1. `scripts/critic/stagnation-check.py`, gate `review` only: a finding with
     `severity == "blocking"` and `kind == "codex"` is `finding_class: "note"`
     and is excluded from the stagnation fingerprint -- same mechanism ticket
     #105 already uses for plan-critic's `simplifier`/`untestable` lenses,
     just keyed on `kind` instead of `lens` because the review gate has no
     lens concept. The severity filter (`severity == "blocking"`) is
     unchanged; only findings that already pass it get the extra kind-based
     split.
  2. Same script, gate `review` only: an additional stdout line,
     `REVIEW_OWN_BLOCKING: <n>` -- the count of findings with
     `severity == "blocking"` and `kind != "codex"`. Nothing extra is printed
     for gates `plan-critic`/`test-critic`.

`skills/process-developer/SKILL.md` Phase 4 will read `REVIEW_OWN_BLOCKING` to
decide routing (implement phase, not here).

Requirement 3 (the cross-file "kind":"codex" token contract between
agents/reviewer.md and scripts/critic/stagnation-check.py) is, after two
rounds of test-critic review, also treated as evidence kind `none` for the
purposes of *this test file* -- see the removal note in the "Requirement 3"
section below for why a dedicated test for it could not be made
non-tautological. Its behavioral substance (a `kind:"codex"` finding is
genuinely excluded from the stagnation fingerprint and from
REVIEW_OWN_BLOCKING) is already exercised end-to-end by Requirement 1/2's
tests above, which construct real `kind: "codex"` fixtures and assert the
gate actually reclassifies/counts based on them.

Requirement 4 (an eventual `review-verdict` prose change naming actual
findings instead of just a count) is evidence kind `none` -- no test for it.

Follows tests/test_plan_critic_convergence.py's conventions for this exact
script family: real subprocess invocation (via `sys.executable`, since
stagnation-check.py is a Python script, not a `.sh` packager), `tmp_path`
fixture files, no model, no network.
"""
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "agents"
CRITIC = REPO_ROOT / "scripts" / "critic"
SKILL = REPO_ROOT / "skills" / "process-developer" / "SKILL.md"
SCRIPT = CRITIC / "stagnation-check.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _write_findings(path: pathlib.Path, findings: list[dict]) -> None:
    path.write_text(json.dumps({"findings": findings}), encoding="utf-8")


def _run(gate: str, findings_path: pathlib.Path, history_path: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), gate, str(findings_path), str(history_path)],
        capture_output=True, text=True, encoding="utf-8",
    )


def _parse_result(stdout: str) -> str:
    m = re.search(r"^RESULT: (progress|stagnation)$", stdout, re.MULTILINE)
    assert m, f"expected a RESULT line in stdout, got: {stdout!r}"
    return m.group(1)


def _parse_own_blocking(stdout: str) -> int:
    m = re.search(r"^REVIEW_OWN_BLOCKING: (\d+)$", stdout, re.MULTILINE)
    assert m, f"expected a REVIEW_OWN_BLOCKING line in stdout, got: {stdout!r}"
    return int(m.group(1))


def _codex_finding(round_num: int, what: str | None = None) -> dict:
    return {
        "id": f"codex-{round_num}",
        "kind": "codex",
        "severity": "blocking",
        "what": what or f"codex reworded observation number {round_num}",
        "file": "scripts/critic/stagnation-check.py",
    }


def _own_finding(round_num: int, what: str | None = None) -> dict:
    return {
        "id": f"own-{round_num}",
        "kind": "correctness",
        "severity": "blocking",
        "what": what or f"reviewer's own blocking issue at round {round_num}",
        "file": "scripts/critic/stagnation-check.py",
    }


# ---------------------------------------------------------------------------
# Requirement 1 -- a Codex-only blocking round is not progress
# ---------------------------------------------------------------------------

def test_codex_only_blocking_round_is_not_progress(tmp_path):
    """Driving test for R1: a review findings block whose every
    severity:"blocking" entry has kind:"codex" must report RESULT: stagnation
    against a fresh (empty) history -- a Codex-only round never contributes a
    fingerprint once Codex findings are note-class, so there is nothing new
    to report as progress. Today's script has no kind-based reclassification
    at all, so this currently reports RESULT: progress (a fresh finding of
    any kind is still "new") -- that is the expected RED reason."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [_codex_finding(1)])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "stagnation", (
        "a Codex-only blocking round must not read as progress once Codex "
        f"findings are note-class; got stdout: {result.stdout!r}"
    )
    assert _parse_own_blocking(result.stdout) == 0


def test_one_own_blocking_finding_is_progress(tmp_path):
    """The same Codex-only round plus one additional non-Codex blocking
    finding must report RESULT: progress -- the reviewer's own finding is a
    genuine new fingerprint regardless of what else is in the round."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [_codex_finding(1), _own_finding(1)])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "progress"
    assert _parse_own_blocking(result.stdout) == 1


def test_nit_severity_codex_finding_does_not_affect_outcome(tmp_path):
    """Additional coverage: a nit-severity Codex finding was never in the
    severity filter to begin with (only "blocking" is), so it must not
    affect the outcome either way -- this pins that the new kind-based split
    only narrows what already passed the severity filter, it does not widen
    it back out."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    nit_codex = {**_codex_finding(1), "severity": "nit"}
    _write_findings(findings_path, [nit_codex])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "stagnation"
    assert _parse_own_blocking(result.stdout) == 0


def test_mixed_codex_and_own_blocking_round_is_progress(tmp_path):
    """Additional coverage: a round with both a Codex blocking finding and an
    own blocking finding is progress (driven by the own finding), and
    REVIEW_OWN_BLOCKING counts only the non-Codex one."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [_codex_finding(1), _codex_finding(2), _own_finding(1)])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "progress"
    assert _parse_own_blocking(result.stdout) == 1


def test_empty_findings_list_is_stagnation(tmp_path):
    """Additional coverage: an empty findings list is stagnation (nothing new
    at all) and reports zero own-blocking findings -- unaffected by this
    ticket's change, pinned here so a future edit cannot silently break it."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "stagnation"
    assert _parse_own_blocking(result.stdout) == 0


def test_plan_critic_gate_is_unaffected_by_kind_based_reclassification(tmp_path):
    """Additional coverage: the kind-based reclassification is scoped to gate
    "review" only. A plan-critic finding tagged kind:"codex" (an unrealistic
    but adversarial input -- plan-critic findings never actually carry this
    kind) must still count toward progress exactly as any other kind would,
    and the script must print only the one RESULT line it always has --
    never a REVIEW_OWN_BLOCKING line, which is review-gate-only."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c1",
         "kind": "codex", "severity": "critical"},
    ])

    result = _run("plan-critic", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "progress", (
        "plan-critic gate must not be affected by review-gate kind-based "
        "reclassification"
    )
    assert "REVIEW_OWN_BLOCKING" not in result.stdout
    non_blank_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(non_blank_lines) == 1, (
        f"plan-critic gate must print exactly one line, got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Requirement 2 -- REVIEW_OWN_BLOCKING is reported every round; replaying real
# recorded sequences ends the gate at or before the soft cap on a Codex-only
# round.
# ---------------------------------------------------------------------------

# Recorded round sequences from real incidents (per-letter round shape):
#   R = a round with a genuine non-Codex blocking finding (plus, realistically,
#       Codex re-raising something too -- Codex findings show up almost every
#       round in both incidents).
#   C = a round whose only blocking findings are Codex's (the reviewer's own
#       findings from earlier rounds are by now fixed).
RECORDED_SEQUENCES = {
    "package_1": "RCCRCCC",  # 7 rounds
    "package_7": "RCCCRR",   # 6 rounds
}


def _walk_sequence(sequence: str, tmp_path: pathlib.Path, seq_name: str):
    """Replays one recorded round sequence through the real script, one
    shared history file for the whole sequence (matching how process-developer
    reuses one generation history file across rounds). Returns the list of
    (result, own_blocking_count) tuples, one per round."""
    history_path = tmp_path / f"{seq_name}-history.json"
    outcomes = []
    for i, letter in enumerate(sequence, start=1):
        findings = [_codex_finding(i, what=f"codex rewords the same point, take {i}")]
        if letter == "R":
            findings.append(_own_finding(i))
        findings_path = tmp_path / f"{seq_name}-round-{i}.json"
        _write_findings(findings_path, findings)

        result = _run("review", findings_path, history_path)
        assert result.returncode == 0, f"round {i} stderr: {result.stderr}"
        outcomes.append((_parse_result(result.stdout), _parse_own_blocking(result.stdout)))
    return outcomes


def test_recorded_round_sequences_end_at_or_before_soft_cap(tmp_path):
    """Driving test for R2: replaying the two recorded incident sequences
    (package #1: R C C R C C C -- 7 rounds; package #7: R C C C R R -- 6
    rounds) must reach a round with REVIEW_OWN_BLOCKING: 0 at or before round
    3 in both cases -- that is the concrete demonstration that a Codex-only
    round stops buying more rounds once the reviewer's own findings are
    resolved, instead of grinding on to the recorded 6-7 rounds. Today's
    script has no REVIEW_OWN_BLOCKING line at all, so parsing it fails
    immediately -- that is the expected RED reason."""
    for seq_name, sequence in RECORDED_SEQUENCES.items():
        outcomes = _walk_sequence(sequence, tmp_path, seq_name)
        own_blocking_counts = [count for _, count in outcomes]

        # F2: the plan's actual Req 2 GREEN condition has a second half that
        # `own_blocking_counts` alone cannot express -- no round may ever
        # satisfy the replan condition (RESULT: stagnation together with
        # REVIEW_OWN_BLOCKING > 0). A plausible bad implementation --
        # "suppress fingerprints whenever a round contains any Codex finding
        # AND the history is already non-empty" -- would pass every
        # assertion above (REVIEW_OWN_BLOCKING is a plain count, unaffected
        # by fingerprint suppression) while still reporting RESULT:
        # stagnation on package_1's round 4 (an "R" round arriving after
        # round 1 already populated the shared history with a codex
        # finding). This assertion, run against every round of both real
        # recorded sequences with their real accumulating history, is what
        # catches that.
        for round_num, (result, count) in enumerate(outcomes, start=1):
            assert not (result == "stagnation" and count > 0), (
                f"{seq_name} round {round_num}: RESULT: stagnation together "
                f"with REVIEW_OWN_BLOCKING: {count} would incorrectly fire "
                "the replan condition while the reviewer's own finding is "
                f"still open -- outcomes were {outcomes}"
            )

        first_zero_round = next(
            (i for i, count in enumerate(own_blocking_counts, start=1) if count == 0),
            None,
        )
        assert first_zero_round is not None, (
            f"{seq_name} ({sequence}): no round ever reported "
            f"REVIEW_OWN_BLOCKING: 0 -- counts were {own_blocking_counts}"
        )
        assert first_zero_round <= 3, (
            f"{seq_name} ({sequence}): first REVIEW_OWN_BLOCKING: 0 round was "
            f"round {first_zero_round}, expected at or before the soft cap "
            f"(round 3) -- counts were {own_blocking_counts}"
        )

        # Sanity: every "R"-lettered round in the sequence must actually have
        # reported a non-zero own-blocking count, and every "C"-lettered
        # round a zero one -- otherwise the fixture itself is wrong, not the
        # script.
        for letter, count in zip(sequence, own_blocking_counts):
            if letter == "R":
                assert count > 0, f"{seq_name}: an 'R' round reported REVIEW_OWN_BLOCKING: 0"
            else:
                assert count == 0, f"{seq_name}: a 'C' round reported REVIEW_OWN_BLOCKING > 0"


def test_own_blocking_every_round_stays_progress_through_soft_cap(tmp_path):
    """Edge case, must not regress ticket #99's case: a synthetic sequence
    where every round raises a genuinely new non-Codex blocking finding must
    still report REVIEW_OWN_BLOCKING > 0 every round, and must still reach
    RESULT: progress through the soft cap (round 3) -- the kind-based split
    must never suppress plain, real progress detection."""
    history_path = tmp_path / "history.json"
    for i in range(1, 4):
        findings = [_own_finding(i, what=f"a genuinely new own issue, round {i}")]
        findings_path = tmp_path / f"round-{i}.json"
        _write_findings(findings_path, findings)

        result = _run("review", findings_path, history_path)
        assert result.returncode == 0, f"round {i} stderr: {result.stderr}"
        assert _parse_result(result.stdout) == "progress", (
            f"round {i}: expected progress (ticket #99's case), "
            f"got stdout: {result.stdout!r}"
        )
        assert _parse_own_blocking(result.stdout) >= 1


def test_review_own_blocking_line_is_review_gate_only(tmp_path):
    """Additional coverage, explicit for R2: the REVIEW_OWN_BLOCKING line
    must never appear for gates plan-critic or test-critic, even though it
    is the same script -- only the gate argument differs."""
    for gate, finding in (
        ("plan-critic", {"id": "1", "title": "t", "what": "w",
                          "violated_criterion": "c1", "kind": "gap", "severity": "critical"}),
        ("test-critic", {"id": "1", "title": "t", "what": "w",
                          "violated_criterion": "c2", "kind": "gap", "severity": "critical"}),
    ):
        findings_path = tmp_path / f"{gate}-findings.json"
        history_path = tmp_path / f"{gate}-history.json"
        _write_findings(findings_path, [finding])

        result = _run(gate, findings_path, history_path)
        assert result.returncode == 0, f"{gate} stderr: {result.stderr}"
        assert "REVIEW_OWN_BLOCKING" not in result.stdout, (
            f"gate {gate} must never print a REVIEW_OWN_BLOCKING line"
        )


def test_non_blocking_severity_own_finding_does_not_count(tmp_path):
    """F3: REVIEW_OWN_BLOCKING must count blocking-severity, non-Codex
    findings only. Every other fixture in this file hard-codes
    severity:"blocking" on its non-Codex ("own") findings, which left the
    severity half of that condition unexercised for a non-Codex finding --
    nothing distinguished "count blocking non-codex findings" (correct) from
    "count all non-codex findings regardless of severity" (wrong -- a
    nit-severity non-Codex finding would then wrongly buy a fix round).

    A nit-severity own finding alone must report REVIEW_OWN_BLOCKING: 0, and
    adding it alongside a genuine blocking own finding must not change that
    finding's count of 1."""
    history_path = tmp_path / "history.json"
    nit_own = {**_own_finding(1), "severity": "nit"}

    findings_path = tmp_path / "findings-nit-only.json"
    _write_findings(findings_path, [nit_own])
    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_own_blocking(result.stdout) == 0
    assert _parse_result(result.stdout) == "stagnation"

    findings_path2 = tmp_path / "findings-nit-plus-blocking.json"
    _write_findings(findings_path2, [nit_own, _own_finding(2)])
    result2 = _run("review", findings_path2, history_path)
    assert result2.returncode == 0, f"stderr: {result2.stderr}"
    assert _parse_own_blocking(result2.stdout) == 1, (
        "a nit-severity own finding must not add to the blocking count "
        f"alongside a genuine blocking one; got stdout: {result2.stdout!r}"
    )


def test_classification_keys_on_kind_field_not_on_id_or_wording(tmp_path):
    """F4: the existing `_codex_finding`/`_own_finding` helpers couple
    `kind:"codex"` with an id/what that also mention "codex", and vice
    versa -- nothing pins classification to the `kind` field specifically,
    as opposed to `id` or the free-text `what`. This breaks that coupling
    both ways.

    A finding with `kind:"codex"` but an id/what that never mentions
    "codex" at all must still be treated as a Codex finding (note-class,
    not counted, and alone in a round it is stagnation) -- proving
    classification does not accidentally key on wording. Conversely, a
    finding with `kind:"correctness"` (not codex) whose id/what happen to
    contain the word "codex" must still count as an own blocker."""
    history_path = tmp_path / "history.json"

    codex_kind_no_wording = {
        "id": "F17",
        "kind": "codex",
        "severity": "blocking",
        "what": "unused variable in helper",
        "file": "x.py",
    }
    findings_path = tmp_path / "findings-codex-kind-no-wording.json"
    _write_findings(findings_path, [codex_kind_no_wording])
    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "stagnation", (
        "a kind:\"codex\" finding must be treated as a Codex finding even "
        f"when nothing in its id/what mentions codex; got: {result.stdout!r}"
    )
    assert _parse_own_blocking(result.stdout) == 0

    correctness_kind_codex_wording = {
        "id": "codex-flavored-typo",
        "kind": "correctness",
        "severity": "blocking",
        "what": "Codex mentioned this typo in its own review comment",
        "file": "y.py",
    }
    findings_path2 = tmp_path / "findings-correctness-kind-codex-wording.json"
    history_path2 = tmp_path / "history2.json"
    _write_findings(findings_path2, [correctness_kind_codex_wording])
    result2 = _run("review", findings_path2, history_path2)
    assert result2.returncode == 0, f"stderr: {result2.stderr}"
    assert _parse_result(result2.stdout) == "progress", (
        "a kind:\"correctness\" finding must count as an own blocker even "
        f"when its id/what mention the word codex; got: {result2.stdout!r}"
    )
    assert _parse_own_blocking(result2.stdout) == 1


def test_second_non_codex_kind_still_counts_as_own_blocking(tmp_path):
    """Round 5 fix: every fixture above that supplies a non-Codex `kind`
    value uses exactly one such value, "correctness" -- nothing distinguishes
    the plan's actual rule, a fixed two-way table ("codex" -> note,
    everything else -> blocking), from an allowlist implementation that only
    treats `kind == "correctness"` as blocking and silently notes every other
    non-Codex kind (including a real reviewer finding kind like "security" or
    "design"). This adds a second, distinct non-Codex kind and asserts it is
    still counted as a blocking own finding -- an allowlist-shaped
    implementation would report REVIEW_OWN_BLOCKING: 0 and RESULT:
    stagnation here instead of the correct 1 / progress."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    security_finding = {
        "id": "sec-1",
        "kind": "security",
        "severity": "blocking",
        "what": "a security-flavored own finding, neither codex nor correctness",
        "file": "scripts/critic/stagnation-check.py",
    }
    _write_findings(findings_path, [security_finding])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_result(result.stdout) == "progress", (
        "a kind:\"security\" blocking finding must count as an own blocker "
        f"under the fixed two-way table; got stdout: {result.stdout!r}"
    )
    assert _parse_own_blocking(result.stdout) == 1, (
        "REVIEW_OWN_BLOCKING must count a kind:\"security\" blocking finding "
        f"as an own blocker, not silently note it; got stdout: {result.stdout!r}"
    )


def test_review_own_blocking_counts_multiple_blocking_own_findings(tmp_path):
    """Major (round 3 test-critic finding): every fixture above that
    exercises REVIEW_OWN_BLOCKING caps the non-Codex blocking count at
    exactly 1 finding per round, so an implementation that renders a
    boolean as a count (e.g. `1 if any_own_blocking else 0`) would pass
    every one of them. This round puts *two* distinct non-Codex blocking
    findings (plus a Codex blocking finding, to confirm Codex is still
    excluded) in the same round and asserts the real count of 2 is
    reported -- a boolean-style implementation would report 1 here, which
    this test must reject."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [
        _codex_finding(1),
        _own_finding(1, what="first distinct own blocking issue"),
        _own_finding(2, what="second distinct own blocking issue"),
    ])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert _parse_own_blocking(result.stdout) == 2, (
        "REVIEW_OWN_BLOCKING must report the real count of blocking "
        "non-codex findings, not a boolean rendered as 0/1; got stdout: "
        f"{result.stdout!r}"
    )
    assert _parse_result(result.stdout) == "progress"


def test_review_gate_stdout_is_exactly_two_lines_in_order(tmp_path):
    """F5 (minor): the review gate's stdout must be exactly two non-blank
    lines, RESULT first then REVIEW_OWN_BLOCKING -- pinning the plan's
    "print a second line after RESULT" shape precisely, not just that both
    substrings appear somewhere."""
    findings_path = tmp_path / "findings.json"
    history_path = tmp_path / "history.json"
    _write_findings(findings_path, [_own_finding(1)])

    result = _run("review", findings_path, history_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2, (
        f"expected exactly two non-blank stdout lines, got: {result.stdout!r}"
    )
    assert lines[0].startswith("RESULT: "), lines
    assert lines[1].startswith("REVIEW_OWN_BLOCKING: "), lines


# ---------------------------------------------------------------------------
# Requirement 3 -- deliberately no test here (round 3 fix)
# ---------------------------------------------------------------------------
#
# Two rounds of isolated test-critic review both found the prior version of
# this section's test tautological, on both halves:
#   - the agents/reviewer.md assertion re-checks a literal in a file this
#     plan declares "Unchanged on purpose" -- it can never go red for any
#     implementation of this ticket -- and it duplicates a pre-existing,
#     pre-ticket test: tests/test_pipeline_contract.py's
#     test_reviewer_returns_a_structured_findings_block already asserts
#     '"kind"' and '"codex"' both appear in agents/reviewer.md.
#   - the stagnation-check.py assertion (`'"codex"' in text`) is satisfiable
#     by a bare comment mentioning "codex", with zero classification
#     behavior behind it.
#
# The test is removed outright rather than narrowed further -- the real
# substance of "the token the reviewer stamps is the token the gate
# classifies on" is already proven, more strongly, by every Req-1/Req-2 test
# above that constructs a `kind: "codex"` fixture and asserts the gate
# actually reclassifies/counts based on it. Requirement 3 is treated as
# evidence kind `none` for this test file (see the module docstring).


# ---------------------------------------------------------------------------
# Requirement 2 (continued) -- the pre-existing fingerprint/history
# mechanism for non-Codex findings survives this change (round 3 fix,
# "Major" #2)
# ---------------------------------------------------------------------------

def test_repeated_identical_own_finding_across_rounds_is_stagnation_by_fingerprint(tmp_path):
    """Regression guard: every other fixture above with a non-Codex blocking
    finding on consecutive rounds uses a *different* `what` text each round
    (see `_own_finding`'s `round_num`-dependent default), which cannot
    distinguish "the count/classification logic was added correctly, on top
    of the unchanged pre-existing fingerprint/history logic" from "an
    implementation that ignores fingerprint history for non-Codex findings
    and just uses the plain per-round count". This replays the *identical*
    (kind, file, what) non-Codex finding across two rounds against one real
    accumulating history file: round 1 must be progress (a fresh
    fingerprint), round 2 must be RESULT: stagnation (the same fingerprint
    already recorded) while REVIEW_OWN_BLOCKING stays 1 both rounds -- the
    finding is still an open own blocker by plain count; only the
    fingerprint-novelty dimension (which drives RESULT) should read
    stagnation on round 2."""
    history_path = tmp_path / "history.json"
    same_what = "the exact same unresolved issue, unchanged since round 1"

    findings_path1 = tmp_path / "round-1.json"
    _write_findings(findings_path1, [_own_finding(1, what=same_what)])
    result1 = _run("review", findings_path1, history_path)
    assert result1.returncode == 0, f"round 1 stderr: {result1.stderr}"
    assert _parse_result(result1.stdout) == "progress"
    assert _parse_own_blocking(result1.stdout) == 1

    findings_path2 = tmp_path / "round-2.json"
    _write_findings(findings_path2, [_own_finding(2, what=same_what)])
    result2 = _run("review", findings_path2, history_path)
    assert result2.returncode == 0, f"round 2 stderr: {result2.stderr}"
    assert _parse_result(result2.stdout) == "stagnation", (
        "replaying the identical own finding must be stagnation by "
        f"fingerprint on round 2; got stdout: {result2.stdout!r}"
    )
    assert _parse_own_blocking(result2.stdout) == 1, (
        "REVIEW_OWN_BLOCKING must stay a plain count of blocking non-codex "
        f"findings regardless of fingerprint novelty; got stdout: {result2.stdout!r}"
    )
