"""
Ticket #118: the installed harness refuses standalone `sleep <n>`, and the
skill forbids `Monitor`/background jobs (#101), so Phase 6's escalating
`Bash("sleep 30/60/120/300")` ladder left a package session with no permitted
way to wait for CI. Phase 6 now waits with one blocking foreground
`project-issues wait-pipeline` call and routes its exit codes.

These tests slice SKILL.md structurally (by heading / list item / sentence),
never by line number. Assertions are per list item and per sentence, not
whole-section substring presence: an exit code's item must route to the right
event and must NOT contain the wrong one. Keyword sets tolerate rewording
(synonyms); they pin the routing semantics, not the phrasing.

  R2 - Phase 6 waits with one foreground `wait-pipeline` call
       (--project/--sha/--timeout 540, Bash timeout 600000), routes exit
       codes 0-5, contains no sleep/Monitor; Phase 5 step 4 links the run
       artefacts.
  R3 - exit 5 (no verdict) and a non-success/non-failure conclusion on the
       exit-4 path never map to green/red; retrigger once (`i`), then blocked.

Scope note (test-critic F1, by design not tightenable): the criterion "the
gate waits" is ultimately a live behaviour of the `project-issues
wait-pipeline` CLI, which is not installed in this repo and cannot be invoked
by an in-repo test; the plan records the live check as a post-release
Dependency. This contract is therefore PROSE-VERIFIED here (structure and
routing of SKILL.md) and the live invocation is a post-release observation.
No fake CLI harness is built on purpose: it would only test itself.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "process-ticket" / "SKILL.md"

_NEG = re.compile(
    r"\b(never|not|no|neither|nor|without|don't|do not|forbidden|refus\w*|prohibit\w*)\b", re.I
)


def _skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def sentences(text: str) -> list[str]:
    """Whitespace-flattened clauses, split at sentence end and semicolons."""
    return [x for x in re.split(r"(?<=[.;!?])\s+", flat(text)) if x]


def negated(sentence: str) -> bool:
    return bool(_NEG.search(re.sub(r"\bno[- ]verdict\b|\bno runs?\b", "", sentence, flags=re.I)))


def unnegated_hits(text: str, pattern: str) -> list[str]:
    """Sentences matching `pattern` that carry no negation/prohibition word,
    i.e. that would read as an instruction to do it."""
    return [x for x in sentences(text) if re.search(pattern, x, re.I) and not negated(x)]


def clauses(text: str) -> list[str]:
    """Sentences further split at commas, semicolons, dashes and brackets, so
    a negation only poisons the clause it sits in."""
    out: list[str] = []
    for x in sentences(text):
        out += [c.strip() for c in re.split(r"[,;()]| [—–] |, ", x) if c.strip()]
    return out


def clause_hit(text: str, *patterns: str) -> bool:
    """True if one un-negated clause of `text` matches every pattern."""
    return any(all(re.search(p, c, re.I) for p in patterns) and not negated(c) for c in clauses(text))


def _section(text: str, heading_prefix: str, level: str = "## ") -> str:
    """Body of the heading starting with `heading_prefix`, up to the next
    heading of the same level."""
    m = re.search(
        r"^" + re.escape(level + heading_prefix) + r".*?$(.*?)(?=^" + re.escape(level) + r"\S|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"heading {level}{heading_prefix!r} not found in SKILL.md"
    return m.group(1)


def _phase6() -> str:
    return _section(_skill(), "Phase 6")


def _exit_bullet(section: str, code: int) -> str:
    """The list item whose head (first 40 chars) names backticked `code`, up
    to the next list item at the same or lower indentation."""
    lines = section.splitlines()
    head = re.compile(r"^([ \t]*)[-*][ \t]+.{0,40}?`" + str(code) + r"`")
    for i, line in enumerate(lines):
        m = head.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        block = [line]
        for nxt in lines[i + 1:]:
            nm = re.match(r"^([ \t]*)[-*][ \t]+", nxt)
            if nm and len(nm.group(1)) <= indent:
                break
            block.append(nxt)
        return "\n".join(block)
    raise AssertionError(f"no list item for exit code `{code}` in Phase 6")


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------


def _call_window(item: str, call: str) -> str:
    """The sentence that carries the call span, plus the next sentence only
    when it opens with a pronoun/the-call (a continuation of the same thought)."""
    sents = sentences(item)
    for i, x in enumerate(sents):
        if call in x:
            nxt = sents[i + 1] if i + 1 < len(sents) else ""
            return x + (" " + nxt if re.match(r"(It|This|That|The call|The wait)\b", nxt) else "")
    raise AssertionError("call span not found in a sentence")


def test_phase6_waits_with_one_blocking_foreground_wait_call():
    items = re.split(r"(?m)^(?=\d+\. )", _phase6())
    hits = [i for i, it in enumerate(items) if re.search(r"`[^`]*project-issues wait-pipeline[^`]*`", flat(it))]
    assert len(hits) == 1, "exactly one Phase 6 step must prescribe the wait-pipeline call"
    idx = hits[0]
    item = flat(items[idx])
    spans = [c for c in re.findall(r"`([^`]+)`", item) if "wait-pipeline" in c and "--project" in c]
    assert len(spans) == 1, "exactly one call span carrying --project"
    call = spans[0]
    assert "--sha" in call and re.search(r"--timeout[ =]540\b", call), "call needs --sha and --timeout 540"
    window = _call_window(item, call)
    # F1: the Bash timeout of 600000 sits in the same clause/parenthesis as the
    # invocation (Bash( ... call ... timeout: 600000 )), or in an un-negated
    # Bash-naming clause of the same window. A stray mention of the number
    # ("the harness caps a call at 600000 ms") does not count.
    tclause = r"timeout\W{0,4}(?:to |of |at )?600000\b"
    in_paren = (re.search(r"\bBash\(", call) and re.search(tclause, call)) or \
        re.search(r"\bBash\([^()]*" + re.escape(call) + r"[^()]*" + tclause + r"[^()]*\)", window)
    assert in_paren or clause_hit(window, r"\bBash\b", tclause), \
        "the Bash call itself must carry timeout 600000 (not a stray mention of the number)"
    # ...and 'foreground' / 'blocking' attach, un-negated, to the call's sentence
    assert clause_hit(window, r"\bforeground\b"), "the call must be described as a foreground call, un-negated"
    assert clause_hit(window, r"\bblocking\b|\bin this turn\b|\bown turn\b"), \
        "the call must be described as blocking / in this turn, un-negated"
    # F3: how <head> is obtained: `git -C <worktree_path> rev-parse HEAD`, in
    # this step or the step just above, stated before the --sha call
    ctx = flat((items[idx - 1] if idx > 0 else "") + " " + items[idx])
    rp = list(re.finditer(r"rev-parse\s+HEAD", ctx))
    assert rp, "the wait step (or the one above) must say how <head> is obtained: rev-parse HEAD"
    assert any(m.start() < ctx.index(call) for m in rp), "rev-parse HEAD must precede the --sha call"
    assert [x for x in sentences(ctx)
            if re.search(r"rev-parse\s+HEAD", x) and re.search(r"\bgit\b.*-C\b|-C\b.*\bgit\b", x)
            and re.search(r"\bhead\b", x, re.I) and not negated(x)], \
        "rev-parse must be an un-negated `git -C <worktree_path> rev-parse HEAD` bound to head"
    # any mention of subagents / dispatching in the wait step must be a prohibition
    lead = flat(re.split(r"(?m)^[ 	]*[-*] ", items[idx], maxsplit=1)[0])  # before the exit-code list
    for x in sentences(lead):
        if re.search(r"subagent|Agent\(|dispatch|Task\(", x, re.I):
            assert negated(x), f"wait step must not delegate the wait: {x!r}"
    # ...and the step must positively say who runs the wait: this session's own
    # turn, or a stated prohibition on delegating it (silence is not enough)
    assert [x for x in sentences(lead)
            if (re.search(r"\b(in|within|during) (this|your|its|the session'?s?|this session'?s?)( own)? (own )?turn\b"
                          r"|\bown turn\b", x, re.I) and not negated(x))
            or (re.search(r"subagent", x, re.I) and negated(x))], \
        "the wait step must state it runs in this session's own turn / never in a subagent"
    assert not unnegated_hits(item, r"background|nohup|Monitor")


def test_phase6_routes_each_exit_code_to_its_own_destination():
    s = _phase6()
    # 0 -> ci-green only
    b0 = flat(_exit_bullet(s, 0))
    assert "ci-green" in b0 and "ci-red" not in b0 and not re.search(r"developer|fix round", b0, re.I)
    # the run id comes from the command's own stdout JSON, not from a lookup
    assert "ci_run" in b0 and re.search(r"\bruns\b", b0) and re.search(r"json|stdout", b0, re.I), \
        "exit 0 must take ci_run (the run id) from `runs` in the command's stdout JSON"
    assert "list_pipeline_runs" not in b0, "exit 0 must not re-look-up the run"
    # 1 -> ci-red (failure path), never ci-green
    b1 = flat(_exit_bullet(s, 1))
    assert "ci-red" in b1 and "ci-green" not in b1
    # 2 / 3 -> same command again, same round, no verdict event, no new round
    for code in (2, 3):
        b = flat(_exit_bullet(s, code))
        assert re.search(r"same (command|call)|again|re-?run|re-?wait", b, re.I), code
        assert re.search(r"same round|(not|never|no)\b[^.]{0,40}(new|another) round", b, re.I), code
        assert "ci-green" not in b and "ci-red" not in b, code
        assert not unnegated_hits(b, r"developer|fix round"), code


def test_phase6_round_accounting_45_minutes_three_rounds_failed():
    s = _phase6()
    assert [x for x in sentences(s)
            if re.search(r"\b45\b", x) and re.search(r"\bmin(ute)?s?\b", x, re.I)
            and re.search(r"\b(round|cap)s?\b", x, re.I)], \
        "the 45-minute round cap must be stated as minutes per round/cap"
    related = " ".join(x for x in sentences(s) if "45" in x or re.search(r"`2`|`3`|repeated", x))
    # a repeated 2/3 is charged against the 45 minutes, NOT counted as a new round
    assert re.search(r"(not|never|no)\b[^.;]{0,60}\b(new|another|separate|extra) round|same round", related, re.I)
    # ...and the sentence that says so ties the repeat to the 45-minute budget
    assert [x for x in sentences(s)
            if re.search(r"\b45\b", x) and re.search(r"\bmin", x, re.I)
            and re.search(r"`2`|`3`|repeat|again", x, re.I)
            and re.search(r"charg|count|against|budget|within|toward|consum|deduct", x, re.I)], \
        "a repeated `2`/`3` must be stated as charged against the 45 minutes"
    assert not unnegated_hits(s, r"(count|open|start)s? (as )?(a |an )?(new|another) round")
    assert [x for x in sentences(s) if re.search(r"\b(three|3)\b[^.;]*round", x, re.I) and "failed" in x], \
        "three CI rounds without green must end in `failed`"
    # the diagnosis chain lives on the exit-1 path, in this order
    b1 = flat(_exit_bullet(s, 1))
    assert "get_pipeline_run" in b1 and "get_pipeline_step_log" in b1, \
        "exit 1 must run get_pipeline_run then get_pipeline_step_log"
    assert b1.index("get_pipeline_run") < b1.index("get_pipeline_step_log"), \
        "get_pipeline_run must come before get_pipeline_step_log"
    # list_pipeline_runs is only the exit-4 fallback, not part of the exit-1 chain
    assert "list_pipeline_runs" not in b1
    assert "list_pipeline_runs" in flat(_exit_bullet(s, 4))


def test_phase6_has_no_sleep_or_monitor():
    s = _phase6()
    assert not re.search(r"\bsleep\b|Start-Sleep|\bMonitor\b", s, re.IGNORECASE)


def test_phase5_step4_instructs_linking_run_dir_and_event_comments():
    body = _section(_skill(), "Phase 5")
    m = re.search(r"^4\. \*\*Compose the PR body\*\*.*?(?=^5\. )", body, re.MULTILINE | re.DOTALL)
    assert m, "Phase 5 step 4 not found"
    hits = [x for x in sentences(m.group(0)) if "<rundir>" in x and "adev:event" in x]
    assert hits, "one sentence must name both <rundir> and the adev:event comments"
    assert [x for x in hits if re.search(r"\b(link|include|add|append|list|Run artefacts)", x, re.I)
            and not negated(x)], "that sentence must be a positive instruction, not a prohibition"
    assert [x for x in hits if re.search(r"URL|link", x, re.I)], "event comments must be linked by URL"
    # the artefacts line precedes the `Closes #<n>` lines in the composed body
    step = flat(m.group(0))
    closes = step.find("Closes #")
    assert closes >= 0, "step 4 must still name the Closes lines"
    assert any(step.find(x) < closes or re.search(r"before[^.;]*Closes", x) for x in hits), \
        "the run-artefacts link must come before the Closes lines"


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------


def test_exit5_first_retrigger_then_second_blocked_never_green_red_or_fix():
    block = flat(_exit_bullet(_phase6(), 5))
    m = re.search(r"\bsecond\b|\btwice\b|already (used|retriggered)", block, re.I)
    assert m, "exit 5 needs a first-time clause and a distinct second-time clause"
    first, second = block[: m.start()], block[m.start():]
    # first occurrence: one retrigger (empty commit, push, re-read head, `i` round)
    assert re.search(r"first|once", first, re.I)
    # F2: each token is bound to an un-negated clause of a sentence about the
    # retrigger (a prohibition of these very commands must not satisfy it)
    retrig = r"re-?trigger|empty commit|--allow-empty|re-?run"
    assert [x for x in sentences(first) if re.search(retrig, x, re.I)
            and clause_hit(x, r"--allow-empty", r"\bpush")], \
        "the retrigger sentence must instruct an empty commit (--allow-empty) and a push, not prohibit them"
    # the retrigger is followed by a re-read of head/sha and a fresh wait on it
    assert [x for x in sentences(first)
            if re.search(r"\b(head|sha)\b", x, re.I)
            and re.search(r"re-?read|re-?resolv|rev-parse|\b(new|fresh|updated|resulting)\b", x, re.I)
            and re.search(r"wait|again|re-?run", x, re.I)
            and not re.search(r"\bsame (head|sha|commit)\b", x, re.I)], \
        "the retrigger must re-read head/the new sha and wait again on it (not the old head)"
    fs = sentences(first)
    assert [x for k, x in enumerate(fs)
            if clause_hit(x, r"`i`|\bi[- ]round|infrastructure round")
            and (re.search(retrig, x, re.I) or (k > 0 and re.search(retrig, fs[k - 1], re.I)))], \
        "the retrigger must be counted as an infrastructure (`i`) round, in a sentence about the retrigger"
    # second occurrence: `blocked`, no continued wait / retrigger, state + url quoted
    ss = sentences(second)
    again = r"wait again|re-?wait|re-?trigger|--allow-empty|re-?run|poll again|try again|another (attempt|wait|retrigger)"
    bk = [k for k, x in enumerate(ss) if clause_hit(x, r"\bblocked\b")]
    assert bk, "the second occurrence must be `blocked` (un-negated)"
    assert not [x for x in ss if [c for c in clauses(x) if re.search(again, c, re.I) and not negated(c)]], \
        "the second occurrence must not wait again or retrigger again"
    k = bk[0]
    window = " ".join(ss[k: k + 2])
    assert clause_hit(window, r"\bstate\b") and clause_hit(window, r"\burls?\b"), \
        "the blocked sentence (or its continuation) must quote state and the run urls, un-negated"
    # never a verdict event or a fix round as an action
    assert not unnegated_hits(block, r"ci-green|ci-red")
    assert not unnegated_hits(block, r"developer|fix round")
    assert any(re.search(r"fix round|developer", x) and negated(x) for x in sentences(block)), \
        "exit 5 must state that it never starts a fix round"


def test_exit4_fallback_classifies_by_conclusion_only():
    block = flat(_exit_bullet(_phase6(), 4))
    assert not re.search(r"\bsleep\b", block, re.I)
    # F4: list_pipeline_runs with commit_sha, called once (not a polling loop)
    lpr = [x for x in sentences(block) if "list_pipeline_runs" in x]
    assert [x for x in lpr if "commit_sha" in x
            and re.search(r"\b(one|a single|single|once)\b", x, re.I) and not negated(x)
            and re.search(r"\b(one|a single|single) (call|lookup|request|query)\b|\bonce\b|\bone[- ]shot\b", x, re.I)], \
        "list_pipeline_runs(commit_sha=...) must be prescribed as a single call, un-negated"
    loop = r"repeat\w*|\buntil\b|poll\w*|\bloops?\b|looping|re-?read\w*|keep (re-?)?(read|call|check|query)\w*"
    assert not [c for x in lpr for c in clauses(x) if re.search(loop, c, re.I) and not negated(c)], \
        "list_pipeline_runs on the exit-4 path must not be attached to repeat/until/poll/loop language"
    assert "conclusion" in block and re.search(r"\bonly\b", block, re.I)
    green = [x for x in sentences(block) if "ci-green" in x and not negated(x)]
    assert green, "the exit-4 fallback must define the ci-green outcome"
    for x in green:
        assert "success" in x and "failure" not in x, f"ci-green must hang on success alone: {x!r}"
    assert [x for x in sentences(block) if "failure" in x and re.search(r"ci-red|`1`|failure path", x)], \
        "failure must route to the ci-red / `1` path"
    other = [x for x in sentences(block)
             if re.search(r"cancelled|timed_out|skipped|any other|otherwise", x, re.I)]
    assert other and any(re.search(r"no[- ]verdict|`5`", x, re.I) for x in other), \
        "other conclusions must defer to the no-verdict (exit 5) handling"
    assert not unnegated_hits(" ".join(other), r"ci-green|ci-red")
    assert [x for x in sentences(block) if "blocked" in x and re.search(r"second|consecutive|twice|again", x, re.I)], \
        "a second consecutive exit 4 must be blocked"
