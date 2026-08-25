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
