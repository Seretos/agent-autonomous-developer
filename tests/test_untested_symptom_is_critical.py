"""
Ticket #108 — a verbatim symptom anchor in the plan, checked at both critic
gates. This file drives requirements 2 and 3 of the #108 plan (generation 2):

  R2: test-critic-package.sh's anchor precondition -- exit 2 (with a reason
      on stderr) when the plan's Test/verification strategy section does not
      open with one of the two `Symptom` anchor forms, exit 0 and verbatim
      carry-through into the assembled package when it does.
  R3: the reshaped severity text and the new "exercised by no test" phrase
      are assembled into the right lens block by both packagers -- the
      tautology lens (test-critic-package.sh) and the missed/untestable
      lenses (plan-critic-package.sh) -- and the plan-critic's four lens
      packages stay byte-identical outside each lens's own PART 5 block.

Requirement 1 (finding_class routing keyed on (lens, severity)) is covered by
additions to tests/test_plan_critic_convergence.py instead, next to the
existing finding_class/blocking_severity_counts tests from ticket #105.

Fixtures live in tests/fixtures/untested-symptom/, shaped after the incident
this ticket cites (Seretos/agent-web-tester#20): a runtime symptom (the first
browser_navigate call fails without a cached Playwright browser) whose only
driving test is a literal/structural check against the source -- it checks
that a particular call and a particular export exist, never that the actual
failing scenario (first call, no cached browser) now succeeds.

None of this calls a model: these are mechanical assembly checks against the
packager scripts' own output (subprocess) and against the static prompt/
constraints text they wrap. Same bash-availability skip convention as
tests/test_release_scripts.py.
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
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "untested-symptom"

SPEC = FIXTURES / "spec.md"
SCOPE = FIXTURES / "scope.md"
PLAN = FIXTURES / "plan.md"
TESTS_DIFF = FIXTURES / "tests.diff"

TEST_CRITIC_PACKAGE = CRITIC / "test-critic-package.sh"
TEST_CRITIC_CONSTRAINTS = CRITIC / "test-critic-constraints.md"
TEST_CRITIC_SYSTEM_PROMPT = CRITIC / "test-critic-system-prompt.txt"
PLAN_CRITIC_PACKAGE = CRITIC / "plan-critic-package.sh"

# The exact sentence the fixture plan.md quotes verbatim from the fixture
# spec.md -- both files must carry it byte-for-byte, checked below.
ANCHOR_SENTENCE = (
    "The first browser_navigate call in a session with no cached Playwright "
    "browser fails with a browser-not-found error instead of installing the "
    "browser and completing the navigation."
)
ANCHOR_LINE = f'Symptom (verbatim from ticket): "{ANCHOR_SENTENCE}"\n'

EXERCISED_BY_NO_TEST_PHRASE = "the acceptance criterion is exercised by no test"

REQUIRE_SHELL_TOOLING = os.environ.get("ADEV_REQUIRE_SHELL_TOOLING") == "1"


# ---------------------------------------------------------------------------
# Shared harness (mirrors tests/test_release_scripts.py's bash-skip convention)
# ---------------------------------------------------------------------------

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


def _run(script: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    _require_bash()
    return subprocess.run(
        [BASH, str(script), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def _plan_without_anchor(tmp_path: pathlib.Path) -> pathlib.Path:
    """A copy of the fixture plan with its Symptom anchor line replaced by an
    ordinary sentence -- simulates a plan the planner wrote before #108, or
    one that dropped the anchor by mistake."""
    text = PLAN.read_text(encoding="utf-8")
    assert ANCHOR_LINE in text, (
        "fixture plan.md must carry the anchor line verbatim for this "
        "helper to be able to strip it -- fixture is broken if this fails"
    )
    stripped = text.replace(ANCHOR_LINE, "Requirements below cover the behaviour.\n")
    dest = tmp_path / "plan-no-anchor.md"
    dest.write_text(stripped, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Fixture sanity (finding tautology::F7: renamed with a `test_fixture_sanity_`
# prefix so these are never mistaken for driving-test evidence of a #108
# requirement -- they check a constant against a fixture added in the same
# batch and can never fail for a #108-related reason. Not part of #108's
# behaviour; they catch a broken fixture before it produces a confusing
# failure two layers down.)
# ---------------------------------------------------------------------------

def test_fixture_sanity_spec_carries_the_anchor_sentence_verbatim():
    assert ANCHOR_SENTENCE in SPEC.read_text(encoding="utf-8")


def test_fixture_sanity_plan_carries_the_anchor_line():
    assert ANCHOR_LINE in PLAN.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# R2 -- test-critic-package.sh anchor precondition
# ---------------------------------------------------------------------------

def test_test_critic_package_rejects_plan_without_anchor(tmp_path):
    """Driving test for R2's exit-2 half. Today test-critic-package.sh has no
    anchor precondition at all and exits 0 unconditionally on a well-formed
    plan/tests pair -- this must currently fail with exit 0 where it expects
    exit 2."""
    bad_plan = _plan_without_anchor(tmp_path)
    out = tmp_path / "package.txt"
    result = _run(TEST_CRITIC_PACKAGE, str(bad_plan), str(TESTS_DIFF), "tautology", str(out))
    assert result.returncode == 2, (
        "test-critic-package.sh must exit 2 when the plan's Test/verification "
        "strategy section does not open with a Symptom anchor line; got exit "
        f"{result.returncode}. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "symptom" in result.stderr.lower() or "anchor" in result.stderr.lower(), (
        f"exit 2 must name the missing anchor on stderr; got:\n{result.stderr}"
    )


def _part1_only(package_text: str) -> str:
    """Slice out PART 1 (the plan, verbatim) specifically -- test-critic-package.sh
    delimits it with the literal banner lines below (see the HEADER/MID1 heredocs
    in that script). Finding tautology::F8: the old assertion searched the whole
    package, so a packager that moved the anchor sentence into PART 2 or PART 4
    instead of leaving it in PART 1 would still have passed it."""
    start = package_text.index("PART 1")
    end = package_text.index("PART 2")
    assert start < end, "PART 1 must precede PART 2 in the assembled package"
    return package_text[start:end]


def test_test_critic_package_accepts_plan_with_anchor_and_carries_symptom_verbatim(tmp_path):
    """Additional coverage for R2's exit-0 half. The packager already `cat`s
    the plan verbatim into the package today, so the verbatim-carry-through
    assertion may already pass before the precondition exists -- only the
    exit-code expectation is new behaviour, asserted here too as part of the
    same requirement.

    Scoped to PART 1 specifically (finding tautology::F8), not the whole
    package: a packager that moved the anchor sentence elsewhere (e.g. duped
    it into PART 2's constraints, or only into PART 4's lens block) must not
    pass this assertion -- the sentence's home is the plan itself."""
    out = tmp_path / "package.txt"
    result = _run(TEST_CRITIC_PACKAGE, str(PLAN), str(TESTS_DIFF), "tautology", str(out))
    assert result.returncode == 0, (
        f"expected exit 0 for a plan carrying the anchor; stderr:\n{result.stderr}"
    )
    package_text = out.read_text(encoding="utf-8")
    part1_text = _part1_only(package_text)
    assert ANCHOR_SENTENCE in part1_text, (
        "the quoted symptom sentence must appear byte-for-byte inside PART 1 "
        "(the plan, verbatim) specifically -- it was not found there:\n"
        f"{part1_text}"
    )


# ---------------------------------------------------------------------------
# R3(a) -- test-critic-package.sh: tautology lens carries the reshaped
# severity bullet, the new finding-title phrase, and (checked directly on the
# static file) the system prompt's precedence sentence.
# ---------------------------------------------------------------------------

def _paragraph_containing(text: str, phrase: str) -> str | None:
    """First blank-line-delimited paragraph of `text` (case-insensitive)
    containing `phrase`, or None. Used to scope an assertion to the specific
    clause carrying a phrase rather than the whole (possibly large) package
    (finding tautology::F2/F3)."""
    low = text.lower()
    needle = phrase.lower()
    idx = low.find(needle)
    if idx == -1:
        return None
    start = low.rfind("\n\n", 0, idx)
    start = 0 if start == -1 else start + 2
    end = low.find("\n\n", idx)
    end = len(text) if end == -1 else end
    return text[start:end]


def test_tautology_package_carries_the_exercised_by_no_test_phrase(tmp_path):
    """Driving test for R3(a)(ii). Nothing in test-critic-package.sh or
    test-critic-constraints.md says this today -- must currently fail.

    Finding tautology::F2: tightened so the phrase must appear as part of a
    clause that ALSO carries severity `critical`, `layer: plan`, and at
    least one of the two stated exemptions (`Symptom: none:<category>` or
    `Substitute execution:`) -- not as a free-floating string anywhere in
    the package, which a wrong/incomplete implementation could satisfy just
    as easily (e.g. by pasting the bare phrase into an unrelated bullet)."""
    out = tmp_path / "package.txt"
    result = _run(TEST_CRITIC_PACKAGE, str(PLAN), str(TESTS_DIFF), "tautology", str(out))
    assert result.returncode == 0, result.stderr
    package_text = out.read_text(encoding="utf-8")
    clause = _paragraph_containing(package_text, EXERCISED_BY_NO_TEST_PHRASE)
    assert clause is not None, (
        "the tautology lens's assembled package must carry the literal "
        f"phrase {EXERCISED_BY_NO_TEST_PHRASE!r} (ticket #108) at all"
    )
    low = clause.lower()
    assert "critical" in low, (
        f"the exercised-by-no-test clause must state severity `critical`:\n{clause}"
    )
    assert "layer" in low and re.search(r"\bplan\b", low), (
        f"the exercised-by-no-test clause must state `layer: plan`:\n{clause}"
    )
    assert "none:<category>" in low or "substitute execution:" in low, (
        "the exercised-by-no-test clause must name at least one of its two "
        f"stated exemptions (`none:<category>` or `Substitute execution:`):\n{clause}"
    )


LITERAL_ASSERTION_BULLET_ANCHOR = "JSON key's mere presence"


def test_tautology_package_carries_the_reshaped_critical_severity(tmp_path):
    """Driving test for R3(a)(i). The literal-string/markdown-heading/JSON-
    key-presence-assertion bullet in test-critic-constraints.md must now
    carry `critical` severity directly adjacent to its own text. Today that
    bullet names no severity at all -- must currently fail.

    Finding tautology::F3: the old assertion used a 300-char proximity
    window between `critical` and the exercised-by-no-test phrase, which
    pre-existing unrelated `critical` text elsewhere in the package (e.g.
    from the F2 clause above, or a future addition) could satisfy without
    the bullet itself ever being reshaped. Tightened to anchor on the
    bullet's own distinguishing text and require `critical` within a much
    tighter window of THAT anchor specifically."""
    out = tmp_path / "package.txt"
    result = _run(TEST_CRITIC_PACKAGE, str(PLAN), str(TESTS_DIFF), "tautology", str(out))
    assert result.returncode == 0, result.stderr
    # Whitespace-normalized (runs of whitespace, including a markdown soft line-wrap, collapsed to
    # a single space): the source prose is hand-wrapped at ~90 columns and the anchor phrase may
    # legitimately straddle a wrap point without that being a defect in the reshaped bullet.
    package_text = re.sub(r"\s+", " ", out.read_text(encoding="utf-8"))
    assert LITERAL_ASSERTION_BULLET_ANCHOR in package_text, (
        "test-critic-constraints.md's literal-string/markdown-heading/"
        "JSON-key-presence assertion bullet must be present, describing all "
        "three patterns, in PART 2 of the package"
    )
    idx = package_text.index(LITERAL_ASSERTION_BULLET_ANCHOR)
    window = package_text[max(0, idx - 150): idx + 150]
    assert re.search(r"critical", window, re.IGNORECASE), (
        "the literal-string-assertion bullet must carry `critical` severity "
        f"directly adjacent to its own text (not just within 300 chars of an "
        f"unrelated phrase elsewhere in the package) -- window checked:\n{window}"
    )


LENS_SPECIFIC_PHRASE = "lens-specific instructions state a severity"
GOVERNS_OVER_GENERAL_PHRASE = "governs over the general"


def _states_lens_specific_governs_over_general(text: str) -> bool:
    """True iff `text` contains one SENTENCE stating both that a package's
    lens-specific instructions state a severity, and that instruction
    governs over the general definitions -- the specific direction ticket
    #108 requires. Sentence-scoped (not "somewhere in the whole text") so
    the two fragments have to be part of the same governing statement, not
    merely both present (finding tautology::F1)."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        low = sentence.lower()
        if LENS_SPECIFIC_PHRASE in low and GOVERNS_OVER_GENERAL_PHRASE in low:
            return True
    return False


def test_system_prompt_carries_the_precedence_sentence():
    """Driving test for R3(a)(iii). test-critic-system-prompt.txt gains one
    sentence: a package's lens-specific severity governs over the general
    severity definitions for that pattern. Not present today.

    Finding tautology::F1: tightened from a bare substring check (which an
    inverted-meaning sentence containing the same words could also satisfy)
    to require both fragments appear together, in the same sentence, stating
    the specific governing direction -- see the negative control below,
    which proves the check actually discriminates direction."""
    text = TEST_CRITIC_SYSTEM_PROMPT.read_text(encoding="utf-8")
    assert _states_lens_specific_governs_over_general(text), (
        "test-critic-system-prompt.txt must state, in one sentence, that a "
        "package's lens-specific severity instructions govern over the "
        "general severity definitions for that pattern (ticket #108) -- not "
        "just mention 'lens-specific' and 'severity' in separate places"
    )


def test_precedence_check_rejects_an_inverted_direction_sentence():
    """Negative control for finding tautology::F1: a hand-written sentence
    claiming the OPPOSITE precedence (the general definitions govern over
    lens-specific instructions) must NOT satisfy
    _states_lens_specific_governs_over_general -- proving the assertion
    above discriminates the governing direction rather than just checking
    that both phrases co-occur somewhere. This string lives only in this
    test file; it is never added to production text."""
    inverted = (
        "Where the general severity definitions above and a package's "
        "lens-specific instructions state a severity for a specific "
        "pattern, the general definitions above govern over the "
        "lens-specific instructions for that pattern."
    )
    assert not _states_lens_specific_governs_over_general(inverted)


# ---------------------------------------------------------------------------
# R3(b) -- plan-critic-package.sh: missed lens carries the anchor-fidelity
# branch, untestable lens carries the symptom carve-out, and all four lenses
# stay byte-identical outside their own PART 5.
# ---------------------------------------------------------------------------

def _run_plan_critic_package(tmp_path, lens):
    out = tmp_path / f"package-{lens}.txt"
    result = _run(PLAN_CRITIC_PACKAGE, str(SPEC), str(SCOPE), str(PLAN), lens, str(out))
    return result, out


# The PART 5 preamble (identical across all four lenses -- see
# test_plan_critic_lenses_stay_byte_identical_outside_their_own_lens_block) ends
# right where plan-critic-package.sh's emit_lens() output begins, and every
# lens's emitted text opens with this exact phrase. Slicing here isolates the
# lens-specific block from PARTs 1-4 -- in particular from PART 4, which is the
# plan verbatim and (via this fixture's own R2 anchor line, "Symptom (verbatim
# from ticket): ...") already contains the words "symptom" and "verbatim from
# ticket" for reasons that have nothing to do with the missed lens's own text.
# A prior version of this test asserted against the whole assembled package
# and passed today for exactly that reason -- a false pass, since the anchor
# line comes from PART 4/the fixture plan, not from any anchor-fidelity text
# LENS_MISSED does not contain yet.
LENS_BLOCK_MARKER = "This run's lens:"


def _lens_block_only(package_text: str) -> str:
    idx = package_text.index(LENS_BLOCK_MARKER)
    return package_text[idx:]


def test_missed_lens_package_carries_the_anchor_fidelity_branch(tmp_path):
    """Driving test for R3(b)'s missed-lens half. Today's LENS_MISSED block
    (plan-critic-package.sh) says nothing about the Symptom anchor's fidelity
    to the ticket -- must currently fail.

    Scoped to the lens block itself (see _lens_block_only above), not the
    whole assembled package: the plan fixture's own R2 anchor line already
    carries "symptom" and "verbatim from ticket" in PART 4, which made an
    earlier, unscoped version of this assertion pass regardless of whether
    LENS_MISSED said anything about anchor fidelity at all.

    Finding tautology::F4: even lens-block-scoped, a bare phrase check
    accepts a fragment carrying no severity, no kind, and no mention of the
    `none:<category>` exemption case. Tightened to require severity
    `critical`, kind `gap`, AND the `none:<category>` mention to appear
    together with the required phrase, in the same paragraph -- not merely
    somewhere else in the (possibly large) lens block."""
    result, out = _run_plan_critic_package(tmp_path, "missed")
    assert result.returncode == 0, result.stderr
    # Whitespace-normalized, same reasoning as the F3 fix above: the lens block is hand-wrapped
    # prose and the required phrase may legitimately straddle a wrap point.
    lens_text = re.sub(r"\s+", " ", _lens_block_only(out.read_text(encoding="utf-8"))).lower()
    required_phrase = "is not the ticket's actual stated runtime symptom"
    assert required_phrase in lens_text, (
        "the missed lens's own PART 5 block (plan-critic-package.sh's "
        "LENS_MISSED heredoc) must gain the anchor-fidelity branch text "
        "(ticket #108): the plan's Symptom anchor is a `critical` `gap` "
        f"when the sentence it quotes {required_phrase!r} -- not found in "
        f"the lens block:\n{lens_text}"
    )
    idx = lens_text.index(required_phrase)
    window = lens_text[max(0, idx - 400): idx + 400]
    assert "critical" in window, (
        f"the anchor-fidelity branch must carry `critical` severity together "
        f"with the required phrase, not elsewhere in the lens block:\n{window}"
    )
    assert re.search(r"\bgap\b", window), (
        f"the anchor-fidelity branch must carry kind `gap` together with the "
        f"required phrase, not elsewhere in the lens block:\n{window}"
    )
    assert "none:<category>" in window, (
        "the anchor-fidelity branch must also cover the case where "
        "`Symptom: none:<category>` is claimed while the specification "
        f"states a runtime symptom, together with the required phrase:\n{window}"
    )


def test_untestable_lens_package_carries_the_symptom_carveout(tmp_path):
    """Driving test for R3(b)'s untestable-lens half. Today's LENS_UNTESTABLE
    block says nothing about a runtime symptom or `Substitute execution:` --
    must currently fail.

    Finding tautology::F5: the old assertion searched the WHOLE assembled
    package, unlike its missed-lens counterpart above, which already scopes
    via `_lens_block_only`. Fixed to use the same isolation helper, and to
    additionally assert the carve-out text is ABSENT from the other three
    lenses' isolated blocks -- catching a degenerate implementation that
    puts the carve-out in a shared PART instead of LENS_UNTESTABLE's own
    block, a false pass the byte-identity control below cannot catch on its
    own (see its docstring, finding tautology::F6)."""
    result, out = _run_plan_critic_package(tmp_path, "untestable")
    assert result.returncode == 0, result.stderr
    lens_text = _lens_block_only(out.read_text(encoding="utf-8")).lower()
    assert "substitute execution" in lens_text, (
        "the untestable lens's own PART 5 block must gain the carve-out "
        "text naming the `Substitute execution:` exemption line (ticket "
        f"#108) -- not found in the lens block:\n{lens_text}"
    )

    for other_lens in ("missed", "misread", "simplifier"):
        other_result, other_out = _run_plan_critic_package(tmp_path, other_lens)
        assert other_result.returncode == 0, other_result.stderr
        other_lens_text = _lens_block_only(other_out.read_text(encoding="utf-8")).lower()
        assert "substitute execution" not in other_lens_text, (
            "the untestable lens's carve-out text must live only inside "
            f"LENS_UNTESTABLE -- found it leaked into the {other_lens!r} "
            f"lens's own block:\n{other_lens_text}"
        )


def test_plan_critic_lenses_stay_byte_identical_outside_their_own_lens_block(tmp_path):
    """Control case, must not regress: PARTs 1-4 (spec, constraints, scope,
    plan) stay byte-identical across all four lenses -- only PART 5 (the
    lens block) differs. #108's text additions live inside each lens's own
    PART 5 block, so this should already pass before and after the change.

    Finding tautology::F6 (the docstring you are reading was rewritten to
    stop overclaiming): this control proves only that PARTs 1-4 do not
    DIVERGE between lenses -- it cannot detect a UNIFORM addition to a
    shared part (e.g. #108 text pasted identically into PART 2 for all four
    lenses), since identical contamination stays byte-identical across
    lenses by construction and this comparison would not notice it. What
    actually catches that degenerate shape is the absence assertion in
    test_untestable_lens_package_carries_the_symptom_carveout above, which
    checks the lens-specific text is ABSENT from the other lenses' own PART
    5 blocks -- not this test."""
    marker = "PART 5"
    texts = {}
    for lens in ("missed", "misread", "untestable", "simplifier"):
        result, out = _run_plan_critic_package(tmp_path, lens)
        assert result.returncode == 0, result.stderr
        texts[lens] = out.read_text(encoding="utf-8")

    def _before_lens_block(text):
        idx = text.index(marker)
        # cut right after the "PART 5 — REVIEW LENS FOR THIS RUN" banner line
        end_of_line = text.index("\n", idx)
        return text[: end_of_line + 1]

    baseline = _before_lens_block(texts["missed"])
    for lens in ("misread", "untestable", "simplifier"):
        assert _before_lens_block(texts[lens]) == baseline, (
            f"PARTs 1-4 diverged between 'missed' and {lens!r}"
        )
