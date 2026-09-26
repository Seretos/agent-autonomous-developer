"""
Structural invariants of the rebuilt package→green-PR pipeline (2026-08 rebuild).

These tests pin the cross-file contract that an orchestrator relies on — the
event vocabulary, the absence of any human-in-the-loop tool, unnamed dispatch,
the critic runners' isolation flags, and the agent roster — without asserting
on prose wording.
"""

import pathlib
import re
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "process-developer" / "SKILL.md"
AGENTS = REPO_ROOT / "agents"
CRITIC = REPO_ROOT / "scripts" / "critic"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

EVENTS = [
    "started", "plan-committed", "plan-critic-verdict", "tests-red",
    "test-critic-verdict", "tests-green", "review-verdict", "pr-opened",
    "ci-red", "replan-triggered", "ci-green", "blocked", "failed",
]
AGENT_NAMES = ["context-extractor", "planner", "plan-critic", "developer",
               "test-critic", "reviewer"]
ISOLATION_FLAGS = ["--setting-sources", "--strict-mcp-config",
                   "--disable-slash-commands", "--tools", "--system-prompt",
                   "--json-schema"]


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "missing YAML front-matter"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


# --- skill surface ----------------------------------------------------------

def test_only_skill_is_process_developer():
    skills = sorted(p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir())
    assert skills == ["process-developer"]


def test_process_developer_is_not_model_invocable():
    fm = _frontmatter(_read(SKILL))
    assert fm.get("name") == "process-developer"
    assert fm.get("disable-model-invocation") == "true"


def test_skill_documents_every_event_exactly_once_in_vocabulary():
    text = _read(SKILL)
    for ev in EVENTS:
        assert f"`{ev}`" in text, f"event {ev} missing from SKILL.md"


def test_skill_declares_terminal_events():
    text = _read(SKILL)
    assert "ci-green" in text and "blocked" in text and "failed" in text
    assert re.search(r"Terminal events", text)


def test_skill_event_block_has_machine_marker():
    text = _read(SKILL)
    assert "<!-- adev:event v1" in text
    for key in ("event:", "package:", "attempt:", "rounds:", "pr:", "ci_run:"):
        assert key in text


def test_skill_requires_all_parameters():
    text = _read(SKILL)
    for p in ("`package`", "`project_id`", "`worktree_path`", "`base_branch`"):
        assert p in text


def test_skill_ci_gate_uses_pipeline_tools():
    text = _read(SKILL)
    for tool in ("list_pipeline_runs", "get_pipeline_run", "get_pipeline_step_log"):
        assert tool in text


def test_skill_never_moves_board_or_asks_human():
    text = _read(SKILL)
    assert "custom_fields" not in text, "the lower plugin must not write board columns"
    assert "update_ticket" not in text
    # AskUserQuestion may only appear in a prohibition, never as an instruction to call it.
    for m in re.finditer(r"AskUserQuestion", text):
        ctx = text[max(0, m.start() - 120): m.end() + 80].lower()
        assert any(w in ctx for w in ("disallowed", "does not exist", "never", "no human")), ctx


def test_event_vocabulary_is_still_closed():
    """Adding an event is a contract change (agent-plugin-dev#26's repair
    lane must reuse the existing names; `replan-triggered` was the one
    deliberate 2026-08-25 addition, documented as such — never a fourteenth,
    silent one)."""
    text = _read(SKILL)
    m = re.search(r"Event names, exhaustively:\s*\n\n(.+?)\n\n", text, re.DOTALL)
    assert m, "could not find the event vocabulary paragraph"
    found = set(re.findall(r"`([a-z-]+)`", m.group(1)))
    assert found == set(EVENTS)


def test_replan_triggered_is_documented_as_non_terminal():
    text = _read(SKILL)
    m = re.search(r"`replan-triggered`[^.]*\bis\b[^.]*not terminal", text)
    assert m, "replan-triggered must be explicitly documented as non-terminal"


def test_generation_field_is_in_the_event_block_and_capped_at_two():
    text = _read(SKILL)
    assert "generation:" in text
    assert "generation < 2" in text or "generation` reaching 2" in text


def test_skill_documents_orientation_and_repair_phases():
    text = _read(SKILL)
    assert "Phase 0" in text and "Phase R" in text
    assert "merge-base --is-ancestor" in text
    assert "origin/<base_branch>..HEAD" in text
    assert "list_pipeline_runs" in text  # used by Phase 0's `finished` check too


def test_skill_reuses_an_open_pr_instead_of_creating_a_second():
    text = _read(SKILL)
    assert "list_prs" in text and "update_pr" in text
    # both tools must be declared in the Hard-rules allowlist, not just prose
    m = re.search(r"Delegate everything.*?Nothing else", text, re.DOTALL)
    assert m and "list_prs" in m.group(0) and "update_pr" in m.group(0)
    # `get_pr`/`merge_pr` must never be *offered* as callable tools — the
    # allowlist sentence enumerates them comma-separated in backticks; the
    # skill is allowed to *say*, in prose, that it deliberately excludes them
    allowlist_sentence = re.search(r"and these MCP calls:.*?\. Nothing else", m.group(0), re.DOTALL)
    assert allowlist_sentence
    enumerated = re.findall(r"`([a-z_]+)`", allowlist_sentence.group(0))
    assert "get_pr" not in enumerated and "merge_pr" not in enumerated


def test_skill_never_bare_force_pushes():
    text = _read(SKILL)
    assert "--force-with-lease" in text
    assert not re.search(r"push\s+(-\S+\s+)*--force(?!-with-lease)", text)


def test_rebase_rounds_gate_is_documented():
    text = _read(SKILL)
    assert "rebase=" in text
    assert re.search(r"rebase\s*\|\s*3", text)


def test_skill_forbids_named_dispatch_and_sendmessage():
    text = _read(SKILL)
    assert "run_in_background: false" in text
    assert "unnamed" in text
    assert re.search(r"never `SendMessage`", text)


# --- agents -----------------------------------------------------------------

def test_agent_roster():
    names = sorted(p.stem for p in AGENTS.glob("*.md"))
    assert names == sorted(AGENT_NAMES)
    for p in AGENTS.glob("*.md"):
        fm = _frontmatter(_read(p))
        assert fm.get("name") == p.stem
        assert fm.get("description")


def test_no_agent_holds_askuserquestion_or_sendmessage():
    for p in AGENTS.glob("*.md"):
        fm = _frontmatter(_read(p))
        tools = fm.get("tools", "")
        assert "AskUserQuestion" not in tools, p.name
        assert "SendMessage" not in tools, p.name


def test_developer_and_reviewer_use_denylists():
    for name in ("developer", "reviewer"):
        fm = _frontmatter(_read(AGENTS / f"{name}.md"))
        assert "disallowedTools" in fm and "tools" not in fm, name
    rv = _frontmatter(_read(AGENTS / "reviewer.md"))["disallowedTools"]
    assert "Edit" in rv and "Write" in rv


def test_developer_has_two_phases():
    text = _read(AGENTS / "developer.md")
    assert "`tests`" in text and "`implement`" in text


def test_critic_agents_reference_existing_runners():
    for agent, runner in (("plan-critic", "plan-critic-run.sh"),
                          ("test-critic", "test-critic-run.sh")):
        text = _read(AGENTS / f"{agent}.md")
        assert runner in text, f"{agent} must call {runner}"
        assert (CRITIC / runner).is_file(), runner
        assert "GATE_RESULT" in text


def test_critic_wrappers_report_blocking_only_findings_with_merged_pointer():
    """Ticket #116 (#113): both critic wrappers stop relaying the full
    findings dump inline and instead report only blocking-class findings,
    in a fixed field order, plus a MERGED: <path> pointer to the file that
    carries everything (note-class findings, merged_from, etc.).

    Round 2 (test-critic tautology::F1-F6): every check below is anchored to
    the actual per-finding template line or the fenced report block itself,
    never to prose that could describe the right shape while the template
    stays unchanged. `## What you report` / `## Hard rules` heading lookups
    below are pure extraction guards (they already succeed against today's
    unedited files); the assertions that follow them are what must fail
    against today's text, and each one is annotated with why it does."""
    for agent, extra_field in (("plan-critic", None), ("test-critic", "layer")):
        text = _read(AGENTS / f"{agent}.md")
        m = re.search(r"## What you report\n(.*?)\n## Hard rules", text, re.DOTALL)
        assert m, f"{agent}.md missing a 'What you report' section"
        section = m.group(1)

        code_block = re.search(r"```\n(.*?)\n```", section, re.DOTALL)
        assert code_block, f"{agent}.md report block missing"
        block = code_block.group(1)
        block_lines = [l for l in block.splitlines() if l.strip()]

        # F1: the listing structure itself must be bounded -- no separate
        # note/blocking class-discriminator field may remain in the
        # per-finding template, since that is exactly what would let a
        # wrapper keep its full verbatim-dump template and merely bolt a
        # "blocking-class only" sentence on top. Today's block still carries
        # `class: <blocking|note>` (plan-critic) -- this must fail RED.
        assert "class:" not in block, (
            f"{agent}.md report block must not carry a class-discriminator "
            "field -- the listing itself must be blocking-only, not merely "
            "described as such alongside an unchanged template")

        # the listing must also be explicitly *described* as blocking-class
        # only (belt-and-braces alongside the structural check above)
        assert re.search(r"blocking[- ]class[^.\n]{0,15}only|only[^.\n]{0,15}blocking[- ]class",
                          section, re.IGNORECASE), \
            f"{agent}.md must state the findings listing is blocking-class only"

        # F3: field order is checked within the actual one-line per-finding
        # template (the line starting "- id:"), never against prose
        # elsewhere in the section that could describe the fields in the
        # right order while the template itself stays wrong. Today's
        # template line carries only id/severity/kind/lens(+class) --
        # violated_criterion and what live on separate lines below it -- so
        # this must fail RED for a real structural reason, not a wording one.
        finding_line = next(
            (l for l in block_lines if l.strip().startswith("- id:")), None)
        assert finding_line, f"{agent}.md report block missing the per-finding template line"
        order_pattern = r"\bid\b.{0,25}\bseverity\b.{0,25}\bviolated_criterion\b.{0,25}\bwhat\b"
        if extra_field:
            order_pattern += rf".{{0,25}}\b{extra_field}\b"
        assert re.search(order_pattern, finding_line), (
            f"{agent}.md per-finding template line must itself order "
            "id|severity|violated_criterion|what"
            + (f"|{extra_field}" if extra_field else "")
            + " -- today's template line splits these across multiple lines"
        )
        # and the collapsed one-liner must actually drop the retired columns,
        # not just reorder around them
        for stale_field in ("kind:", "lens:", "class:"):
            assert stale_field not in finding_line, (
                f"{agent}.md per-finding template line must drop {stale_field} "
                "-- the one-liner keeps exactly the fields named in the plan")

        # F2: only `what` may be truncated to 200 chars. A template that
        # truncates every field to 200 chars must not pass -- so the check
        # requires the *scope between "only" and "truncat[ed]"* to name
        # `what` and nothing else; a phrasing that also states the other
        # three fields are never truncated is fine (that sentence's "only"
        # clause still only spans `what`), but a blanket "all fields ...
        # truncated to 200 chars" (no exclusive "only ... what ... truncat"
        # span) must fail.
        m_only = re.search(r"\bonly\b(?P<mid>.{0,40}?)truncat", section, re.IGNORECASE)
        assert m_only, (
            f"{agent}.md must state, with an explicit 'only ... truncated' "
            "scope, that just `what` is bounded")
        mid = m_only.group("mid").lower()
        assert "what" in mid, f"{agent}.md truncation scope must name `what`"
        for other in ("id", "severity", "violated_criterion"):
            assert other not in mid, (
                f"{agent}.md truncation scope must exclude `{other}` -- "
                "only `what` may be bounded to 200 chars")
        nearby = section[max(0, m_only.start() - 60): m_only.end() + 60]
        assert "200" in nearby, \
            f"{agent}.md must state the 200-char bound near the only-`what`-is-truncated scope"

        # F4: the old verbatim dump (note-class findings, merged_from, the
        # UNVERIFIABLE_... list, solid) must actually be gone from this
        # report section, not merely additive-coexisting with the new
        # sentences above. Checked against the whole section (not just the
        # fenced block) since `solid` is currently introduced in prose right
        # after the block ("Add the `solid` list if it is short.").
        for stale_token in ("merged_from", "UNVERIFIABLE_WITHOUT_CODEBASE_ACCESS", "solid"):
            assert stale_token not in section, (
                f"{agent}.md 'What you report' section must no longer relay "
                f"{stale_token} inline -- it belongs only in "
                "critique-merged.json now")

        # F6: the report ends with a MERGED: <path> pointer that itself
        # looks like a path to critique-merged.json, not a bare label a
        # wrapper could satisfy with unconstrained free text.
        assert block_lines[-1].strip().startswith("MERGED:"), \
            f"{agent}.md report block must end with a MERGED: <path> line"
        merged_line = block_lines[-1]
        assert re.search(r"critique-merged\.json", merged_line), \
            f"{agent}.md MERGED line must point at critique-merged.json"
        assert "/" in merged_line or "absolute" in merged_line.lower(), (
            f"{agent}.md MERGED line must read as a path (absolute-path "
            "shape or an explicit 'absolute' qualifier), not a bare literal")


def test_skill_phase2_and_phase3a_dispatches_name_plan_path_and_merged_json():
    """Ticket #116, reviewer round 1 finding 2: a cross-file consistency gap
    none of the earlier tests covered -- agents/planner.md could gain the
    `plan_path` contract while SKILL.md's own dispatch prose drifts and
    never actually passes it, and nothing would catch that drift. Anchored
    to the specific paragraphs, not a whole-file grep: the Phase 2 round-1
    planner-dispatch sentence, the Phase 2 blocking-critical-to-planner
    handover bullet, and the Phase 3a major/minor-to-3b forwarding bullet.

    RED against the pre-#116 wording (`git show main:skills/process-ticket/SKILL.md`):
    the round-1 dispatch there passes no `plan_path` at all ("Dispatch
    `planner` synchronously and unnamed with `context_summary`,
    `worktree_path`, `recent_changes`"), and both handover bullets forward
    the findings inline ("plus the critical findings" / "forward to 3b as
    notes") rather than a `critique-merged.json` path -- so each assertion
    below fails against main's SKILL.md for a real structural reason, not a
    wording tweak."""
    text = _read(SKILL)

    def section(start_heading, end_heading):
        m = re.search(re.escape(start_heading) + r"\n(.*?)\n" + re.escape(end_heading),
                      text, re.DOTALL)
        assert m, f"missing section {start_heading!r} .. {end_heading!r}"
        return m.group(1)

    phase2 = section(
        "## Phase 2 — planner → plan-critic (question-free)",
        "## Phase 3 — developer, test-first, with the test critique between RED and GREEN")
    phase3 = section(
        "## Phase 3 — developer, test-first, with the test critique between RED and GREEN",
        "## Phase 4 — reviewer")

    # (a) the round-1 planner-dispatch sentence itself must name `plan_path`
    # as an input handed to the planner -- not merely somewhere else in
    # Phase 2 (e.g. only in the surrounding prose paragraph).
    m = re.search(r"[Dd]ispatch `planner` synchronously and unnamed with([^.]*)\.",
                  phase2, re.DOTALL)
    assert m, "Phase 2 round-1 planner-dispatch sentence not found"
    assert "plan_path" in m.group(1), (
        "Phase 2's round-1 planner-dispatch sentence must name `plan_path` "
        "as an input handed to the planner")

    # (b) the blocking-critical-to-planner handover bullet must reference
    # the critique-merged.json path, not inlined findings text.
    m = re.search(r"A \*\*blocking\*\* `critical`.*?critique again\.", phase2, re.DOTALL)
    assert m, "Phase 2 blocking-critical handover bullet not found"
    assert "critique-merged.json" in m.group(0), (
        "Phase 2's blocking-critical-to-planner handover bullet must "
        "reference critique-merged.json rather than inlining the findings text")

    # (c) the Phase 3a major/minor-to-3b forwarding bullet must reference
    # the same path pattern, not a bare "forward ... as notes" with no path.
    m = re.search(r"`major`/`minor` → forward.*?proceed\.", phase3, re.DOTALL)
    assert m, "Phase 3a major/minor forwarding bullet not found"
    assert "critique-merged.json" in m.group(0), (
        "Phase 3a's major/minor-to-3b forwarding bullet must reference "
        "critique-merged.json rather than a bare 'forward as notes' with no path")


def test_context_extractor_expands_epics():
    text = _read(AGENTS / "context-extractor.md")
    assert "list_hierarchy" in _frontmatter(text).get("tools", "")
    assert "transcript" in text.lower()


# --- critic runners ---------------------------------------------------------

def test_runners_carry_the_canonical_isolation_flags():
    for runner in ("plan-critic-run.sh", "test-critic-run.sh"):
        text = _read(CRITIC / runner)
        for flag in ISOLATION_FLAGS:
            assert re.search(rf"^[ \t]*{re.escape(flag)}([ \t]|$)", text, re.M), \
                f"{runner} lost {flag}"
        assert "mktemp -d" in text
        assert "check-critic-isolation.sh" in text


def test_isolation_check_lists_both_runners():
    text = _read(CRITIC / "check-critic-isolation.sh")
    assert "plan-critic-run.sh" in text and "test-critic-run.sh" in text


def test_merge_is_model_free():
    text = _read(CRITIC / "plan-critic-merge.py")
    code = text.split('"""', 2)[-1]  # drop the module docstring
    code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
    for token in ("subprocess", "claude", "anthropic", "requests", "urllib"):
        assert token not in code.lower(), f"the merge must not invoke a model ({token})"


def test_critic_package_files_exist():
    for f in ("plan-critic-package.sh", "plan-critic-schema.json",
              "plan-critic-system-prompt.txt", "plan-critic-constraints.md",
              "test-critic-package.sh", "test-critic-schema.json",
              "test-critic-system-prompt.txt", "test-critic-constraints.md",
              "win-path.sh"):
        assert (CRITIC / f).is_file(), f


def test_no_unity_in_critic_material():
    for p in CRITIC.iterdir():
        assert "unity" not in _read(p).lower(), p.name


# --- stagnation / replan (2026-08-25) ---------------------------------------

def test_stagnation_check_script_exists_and_is_model_free():
    script = CRITIC / "stagnation-check.py"
    assert script.is_file()
    text = _read(script)
    code = text.split('"""', 2)[-1]
    code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
    for token in ("subprocess", "claude", "anthropic", "requests", "urllib"):
        assert token not in code.lower(), \
            f"stagnation-check.py must not invoke a model ({token})"


def test_stagnation_check_supports_all_three_gates():
    text = _read(CRITIC / "stagnation-check.py")
    for gate in ("plan-critic", "test-critic", "review"):
        assert f'"{gate}"' in text or f"'{gate}'" in text


def test_skill_invokes_stagnation_check_at_the_soft_cap():
    text = _read(SKILL)
    assert "stagnation-check.py" in text
    assert "RESULT: progress" in text
    assert "RESULT: stagnation" in text


def test_ci_and_rebase_caps_are_unaffected_by_stagnation_logic():
    text = _read(SKILL)
    m = re.search(r"## Round caps\n\n(.+?)\n\n#", text, re.DOTALL)
    assert m
    assert "6" in m.group(1)  # the new hard cap for plan-critic/test-critic/review
    # CI and rebase must still read as capped at 3, unchanged
    assert re.search(r"CI\s*\|\s*3\s*\|\s*3", m.group(1))
    assert re.search(r"rebase\s*\|\s*3\s*\|\s*3", m.group(1))


def test_reviewer_returns_a_structured_findings_block():
    text = _read(AGENTS / "reviewer.md")
    assert '"findings"' in text
    assert '"kind"' in text and '"severity"' in text
    assert '"codex"' in text  # Codex findings get their own kind


def test_stagnation_check_is_in_the_skills_own_bash_allowlist():
    text = _read(SKILL)
    m = re.search(r"Delegate everything.*?Nothing else", text, re.DOTALL)
    assert m and "stagnation-check.py" in m.group(0)


# --- manifest ---------------------------------------------------------------

def test_plugin_json_depends_only_on_project_issues():
    import json
    d = json.loads(_read(REPO_ROOT / ".claude-plugin" / "plugin.json"))
    deps = [x["name"] for x in d["dependencies"]]
    assert deps == ["agent-project-issues"]


# --- release changelog dispatch (#97) ---------------------------------------

def test_release_workflow_sends_a_changelog_field():
    text = _read(RELEASE_WORKFLOW)
    assert "changelog" in text
    assert "gh release view" in text  # reads back the notes already generated, never a second computation


def test_release_workflow_builds_the_dispatch_payload_with_jq_not_a_bare_heredoc():
    text = _read(RELEASE_WORKFLOW)
    assert "jq -n" in text
    dispatch_step = text.split("Dispatch to agent-marketplace", 1)[1]
    # a real heredoc use is an unindented `<<EOF` starting a shell line, not
    # this pattern mentioned in an explanatory comment (`# ... <<EOF ...`)
    assert not re.search(r"^\s*[^#\n]*<<EOF", dispatch_step, re.MULTILINE)
    assert '-d "$PAYLOAD"' in dispatch_step


def test_release_workflow_still_sends_the_tags_array():
    text = _read(RELEASE_WORKFLOW)
    dispatch_step = text.split("Dispatch to agent-marketplace", 1)[1]
    assert '"git"' in dispatch_step and '"organisation"' in dispatch_step


# --- scripts/event_block.py: deterministic adev:event renderer (#134) ------
#
# The gatekeeper's symptom (Frame comment 5843754508 on #134): posted
# adev:event comments reach the ticket in three shapes (raw, fenced,
# HTML-escaped), with 4 or 5 gates on the `rounds:` line and a trailing
# space after an empty `pr:`/`ci_run:`, so a deterministic external parser
# (ecosystem-statistics) misreads or rejects them. These tests run the new
# renderer as a real subprocess and parse its stdout with a parser that is
# deliberately independent of the renderer's own code, standing in for that
# external parser -- it must catch the renderer being wrong, not agree with
# it by construction.

EVENT_BLOCK = REPO_ROOT / "scripts" / "event_block.py"
GATES = ("plan-critic", "test-critic", "review", "ci", "rebase")

ROUNDS_RE = re.compile(
    r"^rounds: "
    r"plan-critic=(\d+)/3\((\d+)f,(\d+)i\) "
    r"test-critic=(\d+)/3\((\d+)f,(\d+)i\) "
    r"review=(\d+)/3\((\d+)f,(\d+)i\) "
    r"ci=(\d+)/3\((\d+)f,(\d+)i\) "
    r"rebase=(\d+)/3\((\d+)f,(\d+)i\)$"
)


def run_event_block(*args):
    return subprocess.run(
        [sys.executable, str(EVENT_BLOCK), *args],
        capture_output=True, text=True,
    )


def _kv(line, key):
    """Parse a strict `key:` (empty) or `key: <token>` line. Returns None
    (never raises) when the line does not match at all, so callers can
    assert with a useful message."""
    m = re.match(rf"^{re.escape(key)}:(?: (\S+))?$", line)
    return None if m is None else (m.group(1) or "")


def strict_parse_event_block(stdout):
    """Independent strict parser for the `<!-- adev:event v1 ... -->` block,
    standing in for ecosystem-statistics. Raises AssertionError, quoting the
    offending text, on ANY deviation from the one accepted shape (raw, all
    five gates, no trailing whitespace, exactly 9 lines, nothing before the
    marker)."""
    assert stdout.endswith("\n"), f"must end in a trailing newline: {stdout!r}"
    assert not stdout.endswith("\n\n"), f"must end in exactly one trailing newline: {stdout!r}"
    assert stdout.startswith("<!-- adev:event v1\n"), \
        f"nothing may precede the marker: {stdout!r}"
    assert "```" not in stdout, f"must not be fenced: {stdout!r}"
    assert "&lt;" not in stdout and "&gt;" not in stdout, f"must not be HTML-escaped: {stdout!r}"

    lines = stdout[:-1].split("\n")
    assert len(lines) == 9, f"expected exactly 9 lines, got {len(lines)}: {lines!r}"
    assert lines[0] == "<!-- adev:event v1", lines[0]
    assert lines[-1] == "-->", lines[-1]
    for line in lines:
        assert line == line.rstrip(), f"trailing whitespace on line: {line!r}"

    body = lines[1:-1]  # event, package, attempt, generation, rounds, pr, ci_run

    fields = {}
    for key, line in zip(("event", "package", "attempt"), body[:3]):
        v = _kv(line, key)
        assert v is not None, f"bad {key} line: {line!r}"
        fields[key] = v

    m = re.match(r"^generation: (\d+)/2$", body[3])
    assert m, f"bad generation line: {body[3]!r}"
    fields["generation"] = m.group(1)

    m = ROUNDS_RE.match(body[4])
    assert m, f"bad rounds line: {body[4]!r}"
    g = m.groups()
    fields["rounds"] = {
        gate: {"u": g[i * 3], "f": g[i * 3 + 1], "i": g[i * 3 + 2]}
        for i, gate in enumerate(GATES)
    }

    for key, line in zip(("pr", "ci_run"), body[5:7]):
        v = _kv(line, key)
        assert v is not None, f"bad {key} line: {line!r}"
        fields[key] = v

    return fields


# (event, package, attempt, generation, pr, ci_run) -- covers all 13 closed
# events, empty and filled pr/ci_run, and both generation values 1 and 2.
_MATRIX = [
    (EVENTS[0], "pkg-0", "1", "1", "7", "run-0"),
    (EVENTS[1], "pkg-1", "2", "2", "", "run-1"),
    (EVENTS[2], "a--b", "1", "1", "8", ""),
    (EVENTS[3], "pkg-3", "3", "2", "", ""),
    (EVENTS[4], "pkg-4", "1", "1", "9", "run-4"),
    (EVENTS[5], "pkg-5", "1", "2", "", "run-5"),
    (EVENTS[6], "pkg-6", "4", "1", "10", ""),
    (EVENTS[7], "pkg-7", "1", "2", "", ""),
    (EVENTS[8], "pkg-8", "1", "1", "11", "run-8"),
    (EVENTS[9], "pkg-9", "1", "2", "", "run-9"),
    (EVENTS[10], "pkg-10", "5", "1", "12", ""),
    (EVENTS[11], "pkg-11", "1", "2", "", ""),
    (EVENTS[12], "pkg-12", "1", "1", "13", "run-12"),
]
assert {c[0] for c in _MATRIX} == set(EVENTS), "matrix must cover every closed-vocabulary event"
assert "" in {c[4] for c in _MATRIX} and any(c[4] for c in _MATRIX), \
    "matrix must cover both an empty and a filled pr"
assert "" in {c[5] for c in _MATRIX} and any(c[5] for c in _MATRIX), \
    "matrix must cover both an empty and a filled ci_run"
assert {c[3] for c in _MATRIX} == {"1", "2"}, "matrix must cover generation 1 and 2"

# Five distinct non-zero gates, including a U > 3, on every matrix case.
# rebase is deliberately never passed -- its own default is a separate test.
_GATE_ARGS = ["plan-critic=2,1,0", "test-critic=5,0,1", "review=1,1,1", "ci=0,0,3"]
_EXPECTED_GATES = {
    "plan-critic": {"u": "2", "f": "1", "i": "0"},
    "test-critic": {"u": "5", "f": "0", "i": "1"},
    "review": {"u": "1", "f": "1", "i": "1"},
    "ci": {"u": "0", "f": "0", "i": "3"},
}


@pytest.mark.parametrize("event,package,attempt,generation,pr,ci_run", _MATRIX)
def test_event_block_renders_parseable_block(event, package, attempt, generation, pr, ci_run):
    args = ["--event", event, "--package", package, "--attempt", attempt,
            "--generation", generation]
    for g in _GATE_ARGS:
        args += ["--gate", g]
    if pr:
        args += ["--pr", pr]
    if ci_run:
        args += ["--ci-run", ci_run]

    result = run_event_block(*args)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    fields = strict_parse_event_block(result.stdout)

    assert fields["event"] == event
    assert fields["package"] == package
    assert fields["attempt"] == attempt
    assert fields["generation"] == generation
    assert fields["pr"] == pr
    assert fields["ci_run"] == ci_run
    for gate, expected in _EXPECTED_GATES.items():
        assert fields["rounds"][gate] == expected, gate
    assert fields["rounds"]["rebase"] == {"u": "0", "f": "0", "i": "0"}, \
        "an omitted --gate rebase must default to 0,0,0"



# The R1 matrix above reuses one fixed --gate combination on every row, which
# by itself would let a renderer that hardcodes the `rounds:` line pass every
# case there. This dedicated test varies the --gate values themselves across
# several distinct combinations (all five named explicitly, a different
# subset with rebase included, and none at all) and checks each round-trips.
_GATE_COMBOS = [
    ("plan-critic=2,1,0", "test-critic=5,0,1", "review=1,1,1", "ci=0,0,3", "rebase=0,0,0"),
    ("plan-critic=0,4,2", "test-critic=1,0,0", "review=0,0,0", "ci=6,1,0", "rebase=3,2,1"),
    ("plan-critic=1,0,0",),
    (),
]


@pytest.mark.parametrize("gate_args", _GATE_COMBOS,
                         ids=["all-five-distinct", "different-five-distinct",
                              "single-gate-only", "no-gate-flags"])
def test_event_block_varied_gate_combinations_round_trip(gate_args):
    args = ["--event", "started", "--package", "pkg-gatecombo"]
    expected = {name: {"u": "0", "f": "0", "i": "0"} for name in GATES}
    for g in gate_args:
        args += ["--gate", g]
        name, counts = g.split("=")
        u, f, i = counts.split(",")
        expected[name] = {"u": u, "f": f, "i": i}

    result = run_event_block(*args)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    fields = strict_parse_event_block(result.stdout)
    for gate in GATES:
        assert fields["rounds"][gate] == expected[gate], (gate, gate_args)


def test_event_block_empty_pr_and_ci_run_are_bare_keys():
    result = run_event_block("--event", "started", "--package", "pkg-x")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    lines = result.stdout.splitlines()
    assert "pr:" in lines and "ci_run:" in lines
    for line in lines:
        assert not line.startswith("pr: "), "empty pr must be a bare key, no trailing space"
        assert not line.startswith("ci_run: "), "empty ci_run must be a bare key, no trailing space"
    fields = strict_parse_event_block(result.stdout)
    assert fields["pr"] == "" and fields["ci_run"] == ""


def test_event_block_rebase_defaults_to_zero_with_suffix():
    result = run_event_block("--event", "started", "--package", "pkg-y",
                              "--gate", "plan-critic=1,0,0")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    fields = strict_parse_event_block(result.stdout)
    # the gate that *was* passed must round-trip to its own value -- not just
    # the omitted rebase gate's default -- so a renderer that always emits
    # the zero default regardless of --gate could not pass this test.
    assert fields["rounds"]["plan-critic"] == {"u": "1", "f": "0", "i": "0"}
    assert "plan-critic=1/3(0f,0i)" in result.stdout
    assert fields["rounds"]["rebase"] == {"u": "0", "f": "0", "i": "0"}
    assert "rebase=0/3(0f,0i)" in result.stdout


def test_event_block_nine_lines_and_nothing_before_the_marker():
    result = run_event_block("--event", "started", "--package", "pkg-z")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stdout.startswith("<!-- adev:event v1\n")
    assert len(result.stdout.splitlines()) == 9


# --- validation: one whitespace/`-->` rule for every flag value, plus the
# closed-vocabulary and integer/range checks (#134) -------------------------

_BAD_WHITESPACE = {"space": " ", "tab": "\t", "newline": "\n"}


def _bad_argv(flag, bad_value):
    """A valid call for --event/--package, with one flag's value replaced.
    argparse's store action keeps the *last* occurrence of a flag, so
    appending a second --event/--package/--attempt/--generation/--pr/--ci-run
    overrides the valid default above; --gate is an append action, so an
    extra malformed --gate is rejected regardless of the others being fine."""
    return ["--event", "started", "--package", "pkg-v", f"--{flag}", bad_value]


# A base value that is otherwise VALID for the flag it belongs to -- using
# something already-invalid (e.g. a bare "x" for --event/--attempt, which
# fails the vocabulary/integer check on its own) would make the
# whitespace/`-->` case exit 2 for a reason unrelated to the whitespace rule,
# regardless of whether that rule even fires for the flag.
_VALID_BASE = {
    "event": "started",
    "package": "pkgval",
    "attempt": "3",
    "generation": "1",
    "pr": "prval",
    "ci-run": "runval",
    "gate": "plan-critic=1,0,0",
}

# Flags whose bad-value cases also get an *embedded* (mid-value) variant, not
# just a trailing one -- a validator that only inspected the last character
# (or only `str.rstrip()`-compared the value) would wrongly accept these.
_EMBED_FLAGS = ("package", "pr", "ci-run", "gate")

_INVALID_CASES = []
for _flag in ("event", "package", "attempt", "generation", "pr", "ci-run", "gate"):
    _base = _VALID_BASE[_flag]
    for _label, _ws in _BAD_WHITESPACE.items():
        _INVALID_CASES.append((f"{_flag} value contains a trailing {_label}",
                               _bad_argv(_flag, f"{_base}{_ws}")))
    _INVALID_CASES.append((f"{_flag} value contains a trailing arrow",
                           _bad_argv(_flag, f"{_base}-->")))
    if _flag in _EMBED_FLAGS:
        _mid = len(_base) // 2
        for _label, _ws in _BAD_WHITESPACE.items():
            _embedded = _base[:_mid] + _ws + _base[_mid:]
            _INVALID_CASES.append((f"{_flag} value contains an embedded {_label}",
                                   _bad_argv(_flag, _embedded)))
        _embedded_arrow = _base[:_mid] + "-->" + _base[_mid:]
        _INVALID_CASES.append((f"{_flag} value contains an embedded arrow",
                               _bad_argv(_flag, _embedded_arrow)))

_INVALID_CASES += [
    ("unknown event", ["--event", "merged", "--package", "pkg-v"]),
    # a second, differently-fabricated unknown name -- guards against a
    # renderer whose EVENTS tuple drifted to a 14th name that happens not to
    # be "merged" (the closed-vocabulary accept test below only proves the
    # 13 known names are accepted, never that an arbitrary superset addition
    # would be caught).
    ("second unknown event", ["--event", "abandoned", "--package", "pkg-v"]),
    ("unknown gate name", ["--event", "started", "--package", "pkg-v",
                           "--gate", "unknown-gate=1,0,0"]),
    ("duplicate gate", ["--event", "started", "--package", "pkg-v",
                        "--gate", "plan-critic=1,0,0", "--gate", "plan-critic=2,0,0"]),
    ("negative gate count", ["--event", "started", "--package", "pkg-v",
                             "--gate", "plan-critic=-1,0,0"]),
    ("non-integer gate count", ["--event", "started", "--package", "pkg-v",
                                "--gate", "plan-critic=x,0,0"]),
    ("generation too low", ["--event", "started", "--package", "pkg-v", "--generation", "0"]),
    ("generation too high", ["--event", "started", "--package", "pkg-v", "--generation", "3"]),
    ("empty event", ["--event", "", "--package", "pkg-v"]),
    ("empty package", ["--event", "started", "--package", ""]),
    ("negative attempt", ["--event", "started", "--package", "pkg-v", "--attempt", "-1"]),
    ("non-integer attempt", ["--event", "started", "--package", "pkg-v", "--attempt", "abc"]),
]


@pytest.mark.parametrize("label,args", _INVALID_CASES, ids=[c[0] for c in _INVALID_CASES])
def test_event_block_rejects_invalid_input(label, args):
    result = run_event_block(*args)
    assert result.returncode == 2, (label, result.returncode, result.stdout, result.stderr)
    assert result.stdout == "", (label, result.stdout)
    assert result.stderr.startswith("event_block: error:"), (label, result.stderr)


@pytest.mark.parametrize("event", EVENTS)
def test_event_block_accepts_exactly_the_closed_vocabulary(event):
    result = run_event_block("--event", event, "--package", "pkg-v")
    assert result.returncode == 0, (event, result.returncode, result.stdout, result.stderr)
