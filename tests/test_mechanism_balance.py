"""
Ticket #103 — a mandatory "Mechanism balance" section in the plan, a fourth
plan-critic lens ("simplifier") that judges unjustified mechanism growth, and
a reviewer check comparing that balance against the actual diff.

Reason this ticket exists: `lib-python-worktree#148` went through the whole
pipeline clean (plan-critic, test-critic, three review rounds, CI-green) and
still landed a fourth patch on the same module in three weeks, because no
critic and no reviewer was ever asked whether the plan's growth was earned.

Behavioural requirements covered here:

  BR1 — the plan-critic runner recognises exactly the four expected lens ids,
        and every id has a non-empty `emit_lens` branch (a missing branch
        would silently produce an empty PART 5 for that lens).
  BR2 — the `simplifier` lens text prescribes the required verdicts (missing
        balance -> major/gap, unjustified duplicate mechanism -> major/
        double-claim), stays inside the existing `kind` enum, requires a
        package quote before asserting duplication (the lens has no
        repository access), and forbids designing the simpler alternative
        itself.
  BR3 — `plan-critic-schema.json`'s `kind` enum is unchanged (pinned; see
        AGENTS.md, "The plan-critic's fourth lens..." for why no new value
        was added).
  BR4 — the constraints file marks exactly one bullet as quotable
        (STRUCTURAL REQUIREMENT) and carries the canonical mechanism-balance
        sentence the lens's `violated_criterion` must match.
  BR5 — `planner.md` requires the Mechanism balance section and the
        repeat-fix-on-the-same-module default-to-simplification rule, and
        documents `recent_changes` as an input.
  BR6 — `SKILL.md` supplies `recent_changes` to the planner from a `git log`
        call, and `reviewer.md` checks the balance against the diff.
  BR7 — critic prose no longer claims exactly three lenses (narrow regexes;
        legitimate uses of the word "three" elsewhere, e.g. round caps and
        test-critic's own lens count, are untouched).

This is pure text-parsing, no subprocess, no fixtures, no model — matching
`tests/test_pipeline_contract.py`'s convention. Real lens output (does a live
critic actually flag a #148-shaped plan?) is a documented, deliberate testing
gap: see the plan file / PR description for why deterministic contract tests
were chosen over fixture-plan + live-critic tests for this ticket.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "agents"
CRITIC = REPO_ROOT / "scripts" / "critic"
SKILL = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

LENS_IDS = ["missed", "misread", "untestable", "simplifier"]
SCHEMA_KIND_ENUM = ["gap", "contradiction", "double-claim", "risk", "unverified-assumption"]

CANONICAL_BALANCE_SENTENCE = (
    'An implementation plan must carry a mechanism balance: an "Added" list '
    "naming every new module constant, flag or parameter, registry, cache or "
    "lock, tag or reason code, and special-case branch the plan introduces, "
    "each with one line saying why it cannot be avoided by removing or "
    'reshaping something that already exists, and a "Removed" list naming '
    "what the plan deletes."
)


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _list_lenses(text: str) -> list[str]:
    m = re.search(r'^LENS_IDS="([^"]+)"', text, re.M)
    assert m, "LENS_IDS assignment not found in plan-critic-package.sh"
    return m.group(1).split()


def _simplifier_lens_body(text: str) -> str:
    m = re.search(
        r"simplifier\)\s*\n\s*cat <<'LENS_SIMPLIFIER'\n(.*?)\nLENS_SIMPLIFIER",
        text, re.DOTALL,
    )
    assert m, "no simplifier) emit_lens branch found"
    return m.group(1)


# --- BR1: lens roster and emit_lens branches --------------------------------

def test_plan_critic_lens_ids_are_the_four_expected_ones():
    text = _read(CRITIC / "plan-critic-package.sh")
    assert _list_lenses(text) == LENS_IDS


def test_every_lens_id_has_an_emit_branch():
    text = _read(CRITIC / "plan-critic-package.sh")
    for lens in _list_lenses(text):
        m = re.search(
            rf"^\s*{re.escape(lens)}\)\s*\n\s*cat <<'LENS_[A-Z]+'\n(.*?)\nLENS_[A-Z]+",
            text, re.M | re.DOTALL,
        )
        assert m, f"lens id '{lens}' has no emit_lens branch"
        assert m.group(1).strip(), f"lens '{lens}' has an empty PART 5 body"


def test_plan_critic_dot_md_names_all_four_lenses():
    text = _read(AGENTS / "plan-critic.md")
    for lens in LENS_IDS:
        assert f"`{lens}`" in text, f"plan-critic.md must name lens '{lens}'"


# --- BR2: simplifier lens content -------------------------------------------

def test_simplifier_lens_uses_only_kinds_in_the_schema_enum():
    text = _read(CRITIC / "plan-critic-package.sh")
    body = _simplifier_lens_body(text)
    kinds_mentioned = set(re.findall(r"\bkind (\w[\w-]*)", body))
    assert kinds_mentioned, "simplifier lens never prescribes a kind mapping"
    assert kinds_mentioned <= set(SCHEMA_KIND_ENUM), \
        f"simplifier lens uses kind(s) outside the schema enum: {kinds_mentioned - set(SCHEMA_KIND_ENUM)}"


def test_simplifier_lens_makes_a_missing_balance_major():
    body = _simplifier_lens_body(_read(CRITIC / "plan-critic-package.sh"))
    assert "severity major" in body or "major finding" in body
    assert "no such section at all" in body or "missing" in body.lower()


def test_simplifier_lens_makes_a_third_duplicate_mechanism_major():
    body = _simplifier_lens_body(_read(CRITIC / "plan-critic-package.sh"))
    assert "double-claim" in body
    assert "third" in body.lower()


def test_simplifier_lens_requires_a_quote_before_asserting_duplication():
    body = _simplifier_lens_body(_read(CRITIC / "plan-critic-package.sh"))
    assert "no access to the repository" in body.lower() or "no repository access" in body.lower()
    assert "quote" in body.lower()
    # routes unevidenced suspicion to unverifiable_without_codebase_access, in
    # the same words the other lenses/system prompt use for that concept
    assert "cannot verify" in body.lower() or "unverif" in body.lower()


def test_simplifier_lens_forbids_designing_the_alternative():
    body = _simplifier_lens_body(_read(CRITIC / "plan-critic-package.sh"))
    assert re.search(r"do not design", body, re.IGNORECASE)


def test_no_unity_substring_in_simplifier_lens():
    # test_pipeline_contract.py::test_no_unity_in_critic_material already
    # scans the whole file case-insensitively; this pins the specific new
    # lens text so a future edit to it fails locally and fast.
    body = _simplifier_lens_body(_read(CRITIC / "plan-critic-package.sh"))
    assert "unity" not in body.lower()


# --- BR3: kind enum pin ------------------------------------------------------

def test_schema_kind_enum_is_unchanged():
    """No new `kind` value for this ticket — see AGENTS.md, "The
    plan-critic's fourth lens judges mechanism growth, not correctness":
    `kind` drives no routing (severity does) and only feeds the stagnation
    fingerprint, where a lens free to alternate between an old and a new kind
    for the same defect would read as false progress."""
    import json
    schema = json.loads(_read(CRITIC / "plan-critic-schema.json"))
    kind_enum = schema["properties"]["findings"]["items"]["properties"]["kind"]["enum"]
    assert kind_enum == SCHEMA_KIND_ENUM


# --- BR4: constraints file ---------------------------------------------------

def test_constraints_mark_exactly_one_bullet_as_quotable():
    text = _read(CRITIC / "plan-critic-constraints.md")
    # one mention naming the exception in the preamble, one bullet actually
    # marked as it — not two separate quotable bullets
    assert text.count("STRUCTURAL REQUIREMENT") == 2
    assert re.search(r"^- STRUCTURAL REQUIREMENT\.", text, re.M)
    assert "the single exception" in text.lower()


def test_constraints_carry_the_canonical_mechanism_balance_sentence():
    text = _read(CRITIC / "plan-critic-constraints.md")
    # reflowed onto one line, single spaces, exactly as a finding must quote it
    normalized = re.sub(r"\s+", " ", text)
    assert CANONICAL_BALANCE_SENTENCE in normalized


# --- BR5: planner.md ----------------------------------------------------------

def test_planner_requires_a_mechanism_balance_section():
    text = _read(AGENTS / "planner.md")
    assert "**Mechanism balance**" in text
    assert "Added:" in text and "Removed:" in text


def test_planner_defaults_a_repeat_fix_to_simplification():
    text = _read(AGENTS / "planner.md")
    assert "repeat fix" in text.lower()
    assert "14 days" in text
    assert "simplification" in text.lower()


def test_planner_documents_the_recent_changes_input():
    text = _read(AGENTS / "planner.md")
    assert "`recent_changes`" in text


# --- BR6: SKILL.md and reviewer.md -------------------------------------------

def test_skill_supplies_recent_changes_to_the_planner():
    text = _read(SKILL)
    assert "recent_changes" in text
    assert "--since=14.days" in text
    assert re.search(r"git -C <worktree_path> log", text)


def test_skill_names_four_isolated_critics():
    text = _read(SKILL)
    assert "four isolated" in text.lower()


def test_reviewer_checks_the_mechanism_balance_against_the_diff():
    text = _read(AGENTS / "reviewer.md")
    assert "Mechanism balance vs. diff" in text
    assert "[blocking]" in text
    m = re.search(r"Mechanism balance vs\. diff.*?\n", text)
    assert m


# --- BR7: three-lens prose is gone, narrowly ---------------------------------

def test_critic_prose_no_longer_claims_three_lenses():
    narrow_patterns = [
        re.compile(r"\bthe three lenses\b", re.IGNORECASE),
        re.compile(r"all three of us", re.IGNORECASE),
        re.compile(r"other two lenses", re.IGNORECASE),
        re.compile(r"three isolated critics", re.IGNORECASE),
        re.compile(r"three-lens", re.IGNORECASE),
        re.compile(r"three separate Claude CLI processes"),
    ]
    checked = [
        CRITIC / "plan-critic-package.sh",
        CRITIC / "plan-critic-run.sh",
        CRITIC / "plan-critic-merge.py",
        CRITIC / "plan-critic-system-prompt.txt",
        AGENTS / "plan-critic.md",
        SKILL,
        REPO_ROOT / "README.md",
    ]
    for path in checked:
        text = _read(path)
        for pat in narrow_patterns:
            assert not pat.search(text), f"{path.name} still says '{pat.pattern}'"
