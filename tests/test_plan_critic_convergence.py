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
    text = _read(AGENTS / "planner.md")
    assert re.search(r"re-emit the full", text)


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
