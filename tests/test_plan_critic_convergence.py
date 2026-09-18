"""
Ticket #105 — the plan-critic loop converges on an acceptance threshold, not
on zero findings. `lib-python-worktree#154` ran 9 plan-critic rounds across 2
generations (~4.5h, 0 lines of code) because every round against a large plan
reliably surfaced a fresh `untestable`/`simplifier` finding, and the loop
treated every finding as equally blocking. This file pins the mechanism that
fixes it: `plan-critic-merge.py` derives a `finding_class` ("blocking" or
"note") from which lens raised a finding — never a field a critic sets itself
— and `stagnation-check.py` counts only "blocking" findings toward progress.

Three tests here are real unit tests against `plan-critic-merge.py` (imported
by path, since its filename is not a valid Python module name); the rest
follow `tests/test_pipeline_contract.py`'s text-parsing convention. No
subprocess, no model, no fixtures beyond `tmp_path` for the merge tests.
"""

import importlib.util
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "agents"
CRITIC = REPO_ROOT / "scripts" / "critic"
SKILL = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    # same convention as test_pipeline_contract.py's helper of the same name
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "missing YAML front-matter"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def _load_merge_module():
    # scripts/critic/ ships no __pycache__ (see test_pipeline_contract.py's
    # test_no_unity_in_critic_material, which iterates every file in that
    # directory) — suppress bytecode caching for this dynamic import so it
    # doesn't leave one behind.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "plan_critic_merge", CRITIC / "plan-critic-merge.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = previous


def _write_critique(path: pathlib.Path, findings: list[dict]) -> None:
    path.write_text(json.dumps({"findings": findings, "solid": []}), encoding="utf-8")


# --- real unit tests against the merge --------------------------------------

def test_merge_defaults_an_unknown_lens_to_blocking(tmp_path):
    """`tautology` (the test-critic's only lens) is not in the plan-critic
    merge's note set — the merge is shared between both gates
    (test-critic-run.sh:97), and test-critic findings must stay blocking."""
    mod = _load_merge_module()
    critique = tmp_path / "critique-tautology.json"
    _write_critique(critique, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c1",
         "kind": "gap", "severity": "critical"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"tautology={critique}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert len(merged["findings"]) == 1
    assert merged["findings"][0]["finding_class"] == "blocking"


def test_merged_group_takes_the_strongest_class(tmp_path):
    """A `missed` finding (blocking) and a `simplifier` finding (note) sharing
    a byte-identical `violated_criterion` merge into one survivor, chosen by
    severity. Without taking the max class over the group, a real blocking
    finding could be silently declassed to a note just because the
    note-class member happened to carry the higher severity."""
    mod = _load_merge_module()
    same_criterion = "An implementation plan must carry a mechanism balance."
    missed = tmp_path / "critique-missed.json"
    _write_critique(missed, [
        {"id": "1", "title": "t1", "what": "w1", "violated_criterion": same_criterion,
         "kind": "gap", "severity": "major"},
    ])
    simplifier = tmp_path / "critique-simplifier.json"
    _write_critique(simplifier, [
        {"id": "1", "title": "t2", "what": "w2", "violated_criterion": same_criterion,
         "kind": "gap", "severity": "critical"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"missed={missed}", f"simplifier={simplifier}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert len(merged["findings"]) == 1, "same violated_criterion must dedup to one survivor"
    survivor = merged["findings"][0]
    # severity-based survivor selection is unchanged: the critical (simplifier) finding wins
    assert survivor["severity"] == "critical"
    assert survivor["lens"] == "simplifier"
    # but its class is the group's strongest, not its own lens's
    assert survivor["finding_class"] == "blocking"


def test_merge_emits_blocking_severity_counts(tmp_path):
    mod = _load_merge_module()
    missed = tmp_path / "critique-missed.json"
    _write_critique(missed, [
        {"id": "1", "title": "t1", "what": "w1", "violated_criterion": "c-missed",
         "kind": "gap", "severity": "major"},
    ])
    untestable = tmp_path / "critique-untestable.json"
    _write_critique(untestable, [
        {"id": "1", "title": "t2", "what": "w2", "violated_criterion": "c-untestable",
         "kind": "gap", "severity": "major"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"missed={missed}", f"untestable={untestable}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert merged["severity_counts"]["major"] == 2
    assert merged["blocking_severity_counts"]["major"] == 1


# --- Ticket #108: finding_class keyed on (lens, severity), not lens alone ---
#
# lib-python-worktree#154's own root cause (an isolated critic finding
# *something* every round) has a twin at the opposite end: a package whose
# ticket states a runtime symptom but whose only driving tests are
# prose/literal/structure assertions gets graded a `note`-class `untestable`
# finding today no matter how severe, and can reach ci-green with the user's
# actual symptom unfixed. #108 makes an `untestable` finding "blocking" when
# (and only when) its severity is `critical` — the flat lens-only table
# (NOTE_LENSES / finding_class(lens)) cannot express that distinction; the
# driving test below is the one that currently proves it.

def test_untestable_critical_finding_is_blocking_not_note(tmp_path):
    """Driving test for #108's R1: an `untestable`+`critical` finding (the
    ticket's stated symptom is exercised by no test at all) must be
    `finding_class: "blocking"`, not a note the round-cap loop can grind on
    forever. Today's flat lens-only table returns "note" for every
    `untestable` finding regardless of severity -- this must currently fail
    with `"note"` where it asserts `"blocking"`."""
    mod = _load_merge_module()
    untestable = tmp_path / "critique-untestable.json"
    _write_critique(untestable, [
        {"id": "1", "title": "t", "what": "the acceptance criterion is exercised by no test",
         "violated_criterion": "c-untestable-critical", "kind": "gap", "severity": "critical"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"untestable={untestable}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert merged["findings"][0]["finding_class"] == "blocking", (
        "an untestable+critical finding must be blocking under #108's "
        "(lens, severity) table, not the flat lens-only note it gets today")


def test_untestable_major_finding_stays_a_note(tmp_path):
    """Additional coverage: an `untestable`+`major` finding stays a note --
    only `critical` severity promotes it to blocking."""
    mod = _load_merge_module()
    untestable = tmp_path / "critique-untestable.json"
    _write_critique(untestable, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c-untestable-major",
         "kind": "gap", "severity": "major"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"untestable={untestable}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert merged["findings"][0]["finding_class"] == "note"


def test_simplifier_critical_finding_stays_a_note(tmp_path):
    """Control case, must not regress: `simplifier` is a note at every
    severity, including critical -- #108 only touches `untestable`."""
    mod = _load_merge_module()
    simplifier = tmp_path / "critique-simplifier.json"
    _write_critique(simplifier, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c-simplifier-critical",
         "kind": "gap", "severity": "critical"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"simplifier={simplifier}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert merged["findings"][0]["finding_class"] == "note"


def test_missed_and_misread_critical_findings_stay_blocking(tmp_path):
    """Control case, must not regress: `missed`/`misread` stay blocking at
    every severity under the new (lens, severity) table."""
    mod = _load_merge_module()
    missed = tmp_path / "critique-missed.json"
    _write_critique(missed, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c-missed-critical",
         "kind": "gap", "severity": "critical"},
    ])
    misread = tmp_path / "critique-misread.json"
    _write_critique(misread, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c-misread-critical",
         "kind": "gap", "severity": "critical"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"missed={missed}", f"misread={misread}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    classes = {f["violated_criterion"]: f["finding_class"] for f in merged["findings"]}
    assert classes["c-missed-critical"] == "blocking"
    assert classes["c-misread-critical"] == "blocking"


def test_unknown_lens_stays_blocking_at_every_severity(tmp_path):
    """Control case, must not regress: an unnamed lens (the safe default)
    stays blocking regardless of severity."""
    mod = _load_merge_module()
    other = tmp_path / "critique-other.json"
    _write_critique(other, [
        {"id": "1", "title": "t", "what": "w", "violated_criterion": "c-other-minor",
         "kind": "gap", "severity": "minor"},
    ])
    out = tmp_path / "merged.json"
    rc = mod.main(["prog", str(out), f"other-lens={other}"])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert merged["findings"][0]["finding_class"] == "blocking"


# --- D1: acceptance threshold, prose pins ------------------------------------

def test_skill_accepts_at_the_soft_cap_with_no_blocking_critical():
    text = _read(SKILL)
    assert "blocking critical == 0" in text
    assert "always goes back to the planner" not in text  # the pre-#105 simplifier exception is gone


def test_skill_forwards_note_class_findings_to_the_developer():
    text = _read(SKILL)
    assert re.search(r"note.{0,80}forward", text, re.IGNORECASE) or \
        re.search(r"forward.{0,80}note", text, re.IGNORECASE)


def test_stagnation_check_condition_is_pinned_at_the_soft_cap():
    text = _read(SKILL)
    assert "critical == 0" in text


# --- D2: step_assessments removed, working instruction kept -----------------

def test_system_prompt_keeps_the_step_by_step_working_instruction():
    text = _read(CRITIC / "plan-critic-system-prompt.txt")
    assert re.search(r"step by step", text, re.IGNORECASE)
    assert "step-by-step assessments" not in text


# --- D3: evidence kind per requirement ---------------------------------------

EVIDENCE_KINDS = ["driving-test", "existing-suite", "ci-evidence", "none"]


def test_planner_declares_all_four_evidence_kinds():
    text = _read(AGENTS / "planner.md")
    for kind in EVIDENCE_KINDS:
        assert f"`{kind}`" in text, f"planner.md must name evidence kind '{kind}'"


def test_evidence_kind_is_declared_per_requirement():
    text = _read(AGENTS / "planner.md")
    assert "per requirement" in text.lower() or "one per requirement" in text.lower()


def test_untestable_lens_is_scoped_to_driving_test_requirements():
    text = _read(CRITIC / "plan-critic-package.sh")
    m = re.search(
        r"untestable\)\s*\n\s*cat <<'LENS_UNTESTABLE'\n(.*?)\nLENS_UNTESTABLE",
        text, re.DOTALL)
    assert m
    assert "`driving-test`" in m.group(1)


def test_tautology_lens_is_scoped_to_driving_test_requirements():
    text = _read(CRITIC / "test-critic-package.sh")
    m = re.search(
        r"tautology\)\s*\n\s*cat <<'LENS_TAUTOLOGY'\n(.*?)\nLENS_TAUTOLOGY",
        text, re.DOTALL)
    assert m
    assert "`driving-test`" in m.group(1)


def test_constraints_files_scope_test_first_to_driving_test():
    for f in ("plan-critic-constraints.md", "test-critic-constraints.md"):
        text = _read(CRITIC / f)
        assert "driving-test" in text


def test_developer_and_reviewer_scope_evidence_to_driving_test():
    for f in ("developer.md", "reviewer.md"):
        text = _read(AGENTS / f)
        assert "driving-test" in text


def test_test_critic_schema_still_has_assertion_assessments():
    """Open question, not decided by ticket #105: `assertion_assessments` in
    test-critic-schema.json has the same per-assertion redundancy problem
    `step_assessments` had (and the merge already discards it — see
    test-critic-run.sh's comment on why). This test is a deliberate tripwire:
    if this fails, someone removed the field without deciding the question,
    which needs its own ticket, not a silent edit here."""
    schema = json.loads(_read(CRITIC / "test-critic-schema.json"))
    assert "assertion_assessments" in schema["properties"]


# --- D4: plan length budget --------------------------------------------------

def test_planner_states_a_length_budget_and_a_non_growth_rule():
    text = _read(AGENTS / "planner.md")
    assert re.search(r"must not be longer\s+than the round before", text)


def test_planner_still_re_emits_the_full_plan():
    """Ticket #116 (#113): the full plan is still re-emitted on every
    follow-up round, but the destination changes — it goes to `plan_path`
    via `Write`, never into the reply text, which now carries only the
    bounded summary.

    Round 2 (test-critic tautology::F7, F8, F12): the original guard
    (`re.search(r"(re-emit|write) the full[^.\n]*plan[^.\n]*", text)`) is a
    strict superset of the pre-#116 assertion (`re-emit the full`) and
    matches today's unedited file by construction — "re-emit the full
    revised plan" (line ~179) already reads that way when the destination is
    still the reply, not `plan_path`. So the locate step below is split from
    the assertion: candidate re-emission sentences are found first (a pure
    extraction step, expected to match both before and after the edit), and
    the actual behavioural check is that at least one of them names
    `plan_path` as the `Write` destination *in that same sentence* — a 400-
    char trailing window (the old shape) could span several unrelated
    sentences and would trivially "find" plan_path anywhere nearby once it
    exists at all in the file, without it being tied to re-emission at all."""
    text = _read(AGENTS / "planner.md")

    sentences = re.split(r"(?<=[.\n])\s*", text)
    reemission_sentences = [
        s for s in sentences
        if re.search(r"\b(?:re-emit|write)s?\b", s, re.IGNORECASE)
        and re.search(r"\bfull\b[^\n]{0,40}\bplan\b", s, re.IGNORECASE)
    ]
    assert reemission_sentences, "full-plan re-emission rule missing"

    tied_to_plan_path = [
        s for s in reemission_sentences
        if re.search(r"\bWrite\b[^\n]{0,40}\bplan_path\b|\bplan_path\b[^\n]{0,40}\bWrite\b", s)
    ]
    assert tied_to_plan_path, (
        "the full-plan re-emission sentence must name plan_path as the "
        "Write destination in the SAME sentence -- today's file re-emits "
        "the full plan into the reply, with no plan_path mention anywhere "
        "in the document")

    # F8: the reply/status-protocol section must, on its own, state the
    # reply excludes the full plan -- scoped to that section specifically
    # (located the same way "What you report" is located in
    # test_pipeline_contract.py), not a bare whole-file substring search
    # that any incidental occurrence elsewhere in the document would satisfy.
    status = re.search(r"## Status protocol[^\n]*\n(.*?)\n## Hard rules", text, re.DOTALL)
    assert status, "no Status protocol section"
    assert re.search(r"not the full plan", status.group(1), re.IGNORECASE), \
        "the reply's summary must be explicitly distinguished from the full " \
        "plan, inside the reply/status-protocol section itself"

    # R2's contract names a specific bound -- a "≤30-line summary" -- not just
    # a vague "bounded"/"short" summary. Require the actual number (≤30) to
    # be stated, in the same section scope located above, so a future edit
    # that widens or drops the bound (e.g. to 50 lines, or to prose with no
    # number at all) is caught here instead of silently drifting from the
    # plan.
    assert re.search(r"(?:≤\s*30|\bat most 30\b|\b30[-\s]line\b)",
                      status.group(1), re.IGNORECASE), \
        "the reply/status-protocol section must state the ≤30-line bound " \
        "on the summary, not just that it is 'bounded' or 'short'"


# --- #116 R2: planner writes its own plan.md --------------------------------

def test_planner_frontmatter_grants_write_only_for_planning():
    fm = _frontmatter(_read(AGENTS / "planner.md"))
    tools = [t.strip() for t in fm.get("tools", "").split(",")]
    assert "Write" in tools, "planner must hold Write to author plan_path itself"
    assert "Edit" not in tools, "planner must not hold Edit"
    assert "Bash" not in tools, "planner must not hold Bash"


def test_planner_hard_rules_restrict_write_to_plan_path():
    """Round 2 (test-critic tautology::F9, F10, F11): the `## Hard rules`
    heading lookup below is a pure extraction guard -- it already succeeds
    against today's unedited file, which has always had a Hard rules
    section, so it must not be mistaken for evidence of anything. The two
    checks that follow it are the real behavioural assertions, and each
    fails against today's text for a substantive reason (annotated below),
    not because the heading is missing."""
    text = _read(AGENTS / "planner.md")
    m = re.search(r"## Hard rules\n(.*)", text, re.DOTALL)
    assert m, "no Hard rules section"
    hard_rules = m.group(1)

    # F9: co-occurrence of "Write" and "plan_path" is not enough -- a
    # permissive rule naming plan_path plus another allowed Write target
    # would satisfy bare co-occurrence. Require an exclusivity word
    # ("exactly"/"only"/"sole(ly)"/"no other") in the same clause. Today's
    # Hard rules mention neither Write-as-plan_path-destination nor any such
    # word (plan_path does not appear in the file at all yet), so this must
    # fail RED on the *first* assert below, not the exclusivity one.
    write_clause = re.search(
        r"\bWrite\b[^\n]{0,80}\bplan_path\b|\bplan_path\b[^\n]{0,80}\bWrite\b",
        hard_rules)
    assert write_clause, "Hard rules must name plan_path as a Write target"
    clause_text = write_clause.group(0).lower()
    assert re.search(r"\bexactly\b|\bonly\b|\bsole(?:ly)?\b|\bno other\b", clause_text), (
        "Hard rules must state Write is restricted to plan_path exclusively "
        "-- mere co-occurrence with Write is not enough")

    # F10: the "never write a repo file" prohibition must be unconditional.
    # A hedged phrasing ("never ... repo file, unless/except/when ...")
    # containing both tokens must not pass just because both tokens are
    # present. Today's Hard rules contain neither "repo file" nor any
    # occurrence of "never" followed by it within a short span (the current
    # rule is "Never write a ticket comment or open a PR"), so this fails
    # RED on the presence assert, for the genuine reason that the
    # prohibition doesn't exist yet -- not because of a heading or hedge.
    m_never = re.search(r"never[^\n]{0,60}repo file", hard_rules, re.IGNORECASE)
    assert m_never, "Hard rules must forbid writing any repo file"
    hedge = re.search(r"\bunless\b|\bexcept\b|\bwhen\b", m_never.group(0), re.IGNORECASE)
    assert not hedge, "the repo-file prohibition must be unconditional, not hedged"


def test_replan_caps_generation_two_plan_size():
    text = _read(SKILL)
    assert "50" in text or "half" in text.lower()
    assert "plan-generation-1.md" in text or "plan-generation-<g>.md" in text


# --- D5: transcript authorship filter ----------------------------------------

def test_context_extractor_excludes_its_own_event_comments():
    text = _read(AGENTS / "context-extractor.md")
    assert "adev:event" in text
    assert "omit" in text.lower() or "exclude" in text.lower()


def test_transcript_exclusion_is_framed_as_authorship_not_relevance():
    text = _read(AGENTS / "context-extractor.md")
    assert "not on relevance" in text.lower() or "not curation" in text.lower()
    assert "byte-for-byte" in text
    assert "nobody curated it" in text


# --- D6: recent_changes bounded ----------------------------------------------

def test_recent_changes_is_bounded_and_captured_once():
    text = _read(SKILL)
    assert "--max-count" in text
    assert "--since=14.days" in text  # unchanged, pinned since #103
    assert "once per session" in text.lower() or "**once per session**" in text


# --- D7: loosened gates -------------------------------------------------------

def test_developer_no_longer_requires_append_only_evidence():
    text = _read(AGENTS / "developer.md")
    assert "do not overwrite or discard" not in text
    assert "do not overwrite or remove" not in text


def test_reviewer_receives_the_rundir():
    fm_and_body = _read(AGENTS / "reviewer.md")
    assert "`rundir`" in fm_and_body


def test_re_review_is_narrowed_from_round_two():
    text = _read(SKILL)
    assert "never narrowed" not in text
    assert "delta diff" in text.lower()


# --- D8: cache-warm switch and per-lens effort -------------------------------

def test_cache_warm_start_is_a_single_env_switch():
    text = _read(CRITIC / "plan-critic-run.sh")
    assert "ADEV_PLAN_CRITIC_CACHE_WARM" in text


def test_effort_is_parameterised_per_lens():
    text = _read(CRITIC / "plan-critic-run.sh")
    assert "lens_effort" in text
    assert '"medium"' in text or "medium" in text
    assert "--effort \"$effort\"" in text or "--effort" in text


def test_provenance_records_effort_and_start_mode():
    text = _read(CRITIC / "plan-critic-run.sh")
    assert "effort: $effort" in text
    assert "start_mode: $start_mode" in text
