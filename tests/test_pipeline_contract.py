"""
Structural invariants of the rebuilt package→green-PR pipeline (2026-08 rebuild).

These tests pin the cross-file contract that an orchestrator relies on — the
event vocabulary, the absence of any human-in-the-loop tool, unnamed dispatch,
the critic runners' isolation flags, and the agent roster — without asserting
on prose wording.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"
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

def test_only_skill_is_process_ticket():
    skills = sorted(p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir())
    assert skills == ["process-ticket"]


def test_process_ticket_is_not_model_invocable():
    fm = _frontmatter(_read(SKILL))
    assert fm.get("name") == "process-ticket"
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
