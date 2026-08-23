"""
Regression tests for ticket #86: both the B2 teardown sweep and the B6
liveness probe in `skills/orchestrate-tickets/SKILL.md` identify
worktree-bound processes by matching the worktree path as a substring of the
process command line (PowerShell `Get-CimInstance ... CommandLine -like
'*<path>*'`, POSIX `pgrep -f "<path>"`). The probe/sweep's own invocation —
or a helper process its own pipeline forks, such as the `pgrep`-enumerating
command substitution's subshell — can carry that same literal path, so it
can match **itself**, causing B6 to report a genuinely dead/wedged worker as
"alive" (self-matched pwsh.exe, self CPU delta, a PID that drifts between
checks) and B2's teardown sweep to kill the orchestrator's own shell
session.

Current state of the fix, documented in both SKILL.md and AGENTS.md:

- **Self/ancestor/descendant PID exclusion is the load-bearing protection**
  against self-matching. It is evaluated **per candidate, at match time** —
  for every PID in the raw match result, the matcher walks that candidate's
  own parent-PID chain (`ParentProcessId` on Windows, `ppid` on POSIX)
  upward and discards it if the chain reaches the orchestrator's own PID
  (`$PID`/`$$`) or one of its ancestors — never a set precomputed once
  before the match runs and subtracted afterward, which would miss a
  subshell the matcher's own pipeline forks *after* that earlier snapshot
  (e.g. the `pgrep`-enumerating command substitution in the documented
  single `sh -c "AAD_WORKTREE=…; …"` invocation form).
- **Env-var indirection** (`AAD_WORKTREE`) is a distinct, secondary benefit,
  not a second independent self-match-prevention layer: it avoids
  re-embedding the literal (and potentially special-character-laden)
  worktree path directly into the match expression's own text, one
  assignment as a source of truth referenced by variable everywhere the
  match runs.
- **Empty/unset env-var fail-safe**: an empty/unset `AAD_WORKTREE` must
  never fall through to an unscoped wildcard (`-like "**"` / `pgrep -f ""`)
  — both recipes short-circuit to zero survivors instead.
- **ERE/wildcard escaping**: `pgrep -f`'s argument is an extended regular
  expression and PowerShell's `-like` pattern treats `*?[]` as wildcard
  metacharacters, so both recipes escape the worktree path before matching.
- **POSIX B2-kill filters by exe-name/broker before killing** — the raw,
  unfiltered B2-match survivor set is never killed directly.
- **Non-`/proc` fallback**: both the matching side's cwd refinement and the
  exclusion side's ancestor-chain walk have a portable non-Linux fallback
  (`ps -eo pid,ppid`) alongside the `/proc/*/stat` primary path.
- **B6 probe 1 corroboration**: probe 1 (process-alive) only counts toward
  the verdict when its survivor set is non-empty AND PID-stable across
  checks, including a legitimate parent-child re-exec/handoff.

B2 and B6 share exactly one named primitive (`B2-match`, split from the
kill-only `B2-kill`) so the two recipes can never drift apart again.

Red -> green: these tests fail against SKILL.md/AGENTS.md revisions that are
missing any of the above (no PID-exclusion logic, PID-exclusion as a
pre-match snapshot subtraction instead of a per-candidate walk, the worktree
path substituted directly into the match string with no env-var indirection,
the POSIX sweep still an unfiltered `pkill -f "<worktree-path>"`, B6 probe 1
counting alive with no self-exclusion or PID-stability clause, or B6
restating its own matcher inline instead of cross-referencing B2-match by
name) and pass once the hardened primitive and reweighted verdict are
documented in both files.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ORCHESTRATE_MD = REPO_ROOT / "skills" / "orchestrate-tickets" / "SKILL.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _extract_body(text: str) -> str:
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.DOTALL | re.MULTILINE)
    assert fm_end is not None, "Could not find closing '---' of frontmatter"
    return text[fm_end.end():]


def _extract_teardown(body: str) -> str:
    m = re.search(r"## Teardown.*?(?=\n## Hard rules)", body, re.DOTALL)
    assert m, "SKILL.md must contain a '## Teardown' section"
    return m.group(0)


def _extract_sh_fence(text: str) -> str:
    m = re.search(r"```sh\s*\n(.*?)```", text, re.DOTALL)
    assert m, "Teardown must contain a fenced ```sh``` block for the POSIX recipe"
    return m.group(1)


# ---------------------------------------------------------------------------
# BR1 — B2-match excludes self, ancestors, descendants (both OSes)
# ---------------------------------------------------------------------------


def test_b2_match_excludes_self_ancestors_and_descendants():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert re.search(r"B2-match", td), (
        "Teardown must name a 'B2-match' anchor for the shared matching "
        "primitive"
    )
    assert "$PID" in td, (
        "the Windows snippet must reference $PID (the orchestrator's own "
        "PID) as part of the exclusion set"
    )
    assert "ParentProcessId" in td, (
        "the Windows snippet must walk ParentProcessId to build the "
        "ancestor/descendant exclusion chain"
    )
    assert "$$" in td, (
        "the POSIX snippet must reference $$ (the orchestrator's own PID) "
        "as part of the exclusion set"
    )
    assert re.search(r"ppid|ancestor", td, re.IGNORECASE), (
        "the POSIX snippet must walk ppid/ancestor chain for exclusion"
    )
    assert re.search(
        r"self.{0,10}/?.{0,10}ancestor.{0,10}/?.{0,10}descendant|"
        r"self/ancestor/descendant",
        td, re.IGNORECASE,
    ), "Teardown must state self/ancestor/descendant exclusion in prose"
    assert re.search(
        r"before\s+(anything\s+is\s+)?(killed|kill)|before.{0,40}counted?\s+toward\s+liveness",
        td, re.IGNORECASE,
    ), (
        "Teardown must state the exclusion set is computed BEFORE anything "
        "is killed or counted toward liveness"
    )


def test_b2_match_precomputes_orchestrator_ancestor_set_for_reverse_case():
    """Strengthened BR1 (final ticket #86 fix round). The original
    Test-SelfAncestorOrDescendant-style walk (candidate PID upward through
    the parent map, checking for $PID/$$) only ever catches two of the
    three exclusion cases: self (candidate IS the orchestrator) and
    DESCENDANT (walking up from the candidate reaches the orchestrator).
    It can never catch the reverse case — a candidate that is itself an
    ANCESTOR of the orchestrator (e.g. a wrapper/launcher shell that
    spawned the orchestrator and independently matches the worktree-path
    substring via its own cwd or invocation text) — because that walk only
    ever moves in one direction (candidate -> parent -> grandparent -> …)
    and an ancestor of the orchestrator lies in the opposite direction.

    Catching the reverse case requires a genuinely separate precomputed
    set: the orchestrator's own ancestor chain, walked ONCE from $PID/$$
    upward, with each candidate's PID then checked for membership in that
    set independently of the candidate-upward walk. A loose "do the words
    ancestor/descendant/self appear" check (the original, now-superseded
    version of this test) passes against the pre-fix, self+descendant-only
    code too, since that prose already used those words throughout — this
    test instead requires the concrete precomputation/lookup shape, not
    just the vocabulary.

    Red -> green: fails against the self+descendant-only implementation
    (no $PID/$$-anchored ancestor-set precomputation, no membership check
    against it) and passes once that precomputation and lookup exist on
    both the Windows and POSIX recipes.
    """
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    # Windows: a set/hashtable built by walking UP from $PID itself (not
    # from a candidate PID), populated before the per-candidate check runs,
    # and then consulted when building $survivors.
    assert re.search(r"\$walkPid\s*=\s*\$PID\b", td), (
        "Windows recipe must walk up from $PID itself (not just from each "
        "candidate) to build the orchestrator's own ancestor-PID set"
    )
    assert re.search(r"orchestratorAncestorPids", td), (
        "Windows recipe must precompute a named orchestrator-ancestor-PID "
        "set/hashtable, not just reuse the candidate-upward walk"
    )
    assert re.search(
        r"orchestratorAncestorPids\.ContainsKey\(\s*\$_\.ProcessId\s*\)",
        td,
    ), (
        "Windows recipe must check each raw-match candidate's PID for "
        "membership in the precomputed orchestrator-ancestor set when "
        "building $survivors"
    )

    # POSIX: a list built by walking UP from $$ itself (not from a
    # candidate PID), populated before the per-candidate loop runs, and
    # then consulted per candidate.
    assert re.search(r'walk_pid=\$\(get_ppid\s+"\$\$"\)', td), (
        "POSIX recipe must walk up from $$ itself (not just from each "
        "candidate) to build the orchestrator's own ancestor-PID set"
    )
    assert re.search(r"orchestrator_ancestor_pids", td), (
        "POSIX recipe must precompute a named orchestrator-ancestor-PID "
        "list/set, not just reuse the candidate-upward walk"
    )
    assert re.search(
        r'"\s*\$orchestrator_ancestor_pids\s*"[\s\S]{0,40}candidate_pid',
        td,
    ), (
        "POSIX recipe must check each candidate's PID for membership in "
        "the precomputed orchestrator-ancestor set before deciding "
        "is_self_or_ancestor"
    )


# ---------------------------------------------------------------------------
# BR2 — matcher never embeds the literal path in its own command line
# ---------------------------------------------------------------------------


def test_matcher_uses_env_var_indirection_not_path_literal():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert "$env:AAD_WORKTREE" in td, (
        "the Windows matcher must use $env:AAD_WORKTREE indirection, not "
        "the literal worktree path inline"
    )
    assert "AAD_WORKTREE" in td and re.search(r"\$AAD_WORKTREE", td), (
        "the POSIX matcher must use $AAD_WORKTREE indirection"
    )
    assert re.search(
        r"separate\s+preceding\s+statement|preceding\s+statement",
        td, re.IGNORECASE,
    ), (
        "Teardown must state the env-var assignment is a separate preceding "
        "statement, not inline with the match"
    )
    assert re.search(
        r"command('s)?\s+own\s+command.?line|"
        r"one\s+(command\s+string|single\s+shell\s+invocation)|"
        r"wrapping\s+process'?s?\s+own\s+command.?line",
        td, re.IGNORECASE,
    ), (
        "Teardown must explain WHY a naive command-line scan can still "
        "self-match: when assignment+match are issued as one invocation, "
        "the wrapping process's own command line still carries the "
        "literal path"
    )
    assert re.search(
        r"env(ironment)?\s+(variable\s+)?(doesn'?t|does\s+not)\s+persist|"
        r"if\s+env\s+doesn'?t\s+persist",
        td, re.IGNORECASE,
    ), (
        "Teardown must document the PID-filter-alone fallback if the env "
        "var doesn't persist between calls"
    )

    # The old style of substituting the literal worktree-path placeholder
    # directly into a `-like`/`pgrep -f` match expression must be gone.
    assert not re.search(r"-like\s+'\*<worktree-path>\*'", td), (
        "the Windows match expression must no longer inline the literal "
        "worktree-path placeholder"
    )
    assert 'pgrep -f "<worktree-path>"' not in td, (
        "the POSIX match must no longer inline the literal worktree-path "
        "placeholder directly into pgrep -f"
    )


# ---------------------------------------------------------------------------
# BR3 — POSIX sweep is pgrep-filtered with /proc-cwd refinement; unfiltered
# `pkill -f` is gone entirely
# ---------------------------------------------------------------------------


def test_posix_sweep_is_pgrep_filtered_not_unfiltered_pkill():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert "pgrep -f" in td, "Teardown must use pgrep -f to enumerate candidates"
    assert "/proc/" in td, "Teardown must reference /proc/ for cwd refinement"
    assert "cwd" in td, "Teardown must reference matching against process cwd"
    assert "kill -TERM" in td, "Teardown must TERM survivors first"
    assert "kill -KILL" in td, "Teardown must KILL any stragglers still alive"

    # Negative guard: the literal unfiltered-by-path kill string must be gone
    # from the ENTIRE file, not just Teardown.
    full_body = _extract_body(_read(ORCHESTRATE_MD))
    assert "pkill -f" not in full_body, (
        "the literal string 'pkill -f' must not remain anywhere in "
        "SKILL.md — the unfiltered by-path kill sweep has been replaced"
    )


# ---------------------------------------------------------------------------
# BR6 (round 3, Codex finding 1) — POSIX B2-kill applies the exe-name /
# app-server-broker.mjs filter before killing, mirroring Windows's B2-kill;
# it must not kill B2-match's raw, unfiltered survivor set directly.
# ---------------------------------------------------------------------------


def _extract_posix_b2_kill_stage(td: str) -> str:
    """Isolate the POSIX B2-kill stage specifically — from the
    '**B2-kill, POSIX**' heading to the start of Teardown step 2 (which
    isn't part of B2 at all) — rather than the whole Teardown section. A
    prior version of this test's assertions ran against all of Teardown,
    which let a stray, unrelated occurrence of a required substring
    anywhere in Teardown pass the test even if it were missing from the
    POSIX B2-kill stage itself."""
    m = re.search(
        r"\*\*B2-kill, POSIX\*\*.*?(?=\n2\. \*\*Confirm the directory is free)",
        td, re.DOTALL,
    )
    assert m, "Teardown must contain a '**B2-kill, POSIX**' stage"
    return m.group(0)


def test_posix_b2_kill_filters_by_exe_name_before_killing():
    """(F3/A6, ticket #86) Rewritten to be scoped and precise: (a) extracts
    the POSIX B2-kill stage substring specifically, not the whole Teardown
    section; (b) requires each allowlist name in BACKTICKED form so `uv`
    cannot pass off matching inside `uvx`, and `node` cannot pass off the
    Windows `node.exe` mention; (c) requires the literal `ps -o comm=,args=
    -p` with no dead OR-branch; (d) asserts ordering POSITIONALLY (the
    filter step's text index is less than `kill -TERM`'s text index) within
    the POSIX stage substring, in place of the old regex whose second
    alternative (`before\\s+killing.{0,10}`) could pass by coincidence
    regardless of what actually preceded/followed 'killing' — demonstrated
    via mutation testing in this ticket's change report: the OLD assertions
    passed even against a version of the text with the POSIX allowlist line
    removed entirely, while these NEW assertions correctly fail on that same
    mutation.
    """
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    stage = _extract_posix_b2_kill_stage(td)

    # There must be a distinctly-labeled POSIX B2-kill stage, separate from
    # B2-match, exactly like the Windows split already has.
    assert re.search(r"B2-kill,\s*POSIX", td), (
        "Teardown must contain a separately-labeled 'B2-kill, POSIX' stage, "
        "mirroring 'B2-kill, Windows/PowerShell'"
    )

    # The POSIX exe-name allowlist (the five Windows names without .exe)
    # must appear together, applied before the kill, and in BACKTICKED form
    # specifically — so `uv` can't pass off matching inside `uvx`, and
    # `node` can't pass off the Windows `node.exe` mention elsewhere in the
    # file.
    for name in ("node", "uvx", "uv", "serena", "python"):
        assert re.search(rf"`{name}`", stage), (
            f"POSIX B2-kill must name `{name}` (backticked) in its "
            "exe-name allowlist"
        )
    assert "app-server-broker.mjs" in stage, (
        "POSIX B2-kill must also filter on the app-server-broker.mjs "
        "command-line match, like Windows's B2-kill"
    )
    assert "ps -o comm=,args= -p" in stage, (
        "POSIX B2-kill must inspect each survivor PID's command name/args "
        "via the literal `ps -o comm=,args= -p` before deciding to kill it"
    )

    # Positional ordering: the filter step (ps -o comm=,args= -p) must
    # appear BEFORE kill -TERM in the stage's text, not merely somewhere in
    # the same paragraph regardless of order.
    filter_idx = stage.index("ps -o comm=,args= -p")
    term_idx = stage.index("kill -TERM")
    assert filter_idx < term_idx, (
        "POSIX B2-kill must filter the survivor set (ps -o comm=,args= -p) "
        "BEFORE kill -TERM runs, not kill the raw B2-match survivor set "
        "directly"
    )


# ---------------------------------------------------------------------------
# BR7 (round 3, Codex finding 2) — POSIX self/ancestor/descendant exclusion
# has a working descendant-tree fallback on non-/proc systems (macOS/BSD),
# not just the matching side's existing pgrep-alone fallback.
# ---------------------------------------------------------------------------


def test_posix_descendant_exclusion_has_non_proc_fallback():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert re.search(r"ps -eo pid,ppid", td), (
        "Teardown must document a `ps -eo pid,ppid` based descendant-tree "
        "walk as the non-/proc (macOS/BSD) fallback for self/ancestor/"
        "descendant exclusion, mirroring the matching side's own "
        "/proc-vs-pgrep-alone fallback split"
    )
    assert re.search(
        r"macOS|BSD", td,
    ), (
        "the descendant-exclusion recipe must explicitly name macOS/BSD as "
        "the non-/proc fallback case, not just the matching side"
    )
    # The /proc walk must remain the primary/fast path on Linux, not be
    # replaced outright.
    assert "/proc/*/stat" in td, (
        "the /proc/*/stat forward walk must remain the primary descendant-"
        "tree discovery path on Linux"
    )


# ---------------------------------------------------------------------------
# BR9 (round 6, Codex finding 2) — an empty/unset AAD_WORKTREE must not
# degrade B2-match into an unscoped wildcard match. Both the Windows and
# POSIX B2-match recipes must guard on the env var being non-empty/set and
# yield zero survivors, full stop, when it is empty/unset — a guarantee
# independent of (and not rescued by) the self/ancestor/descendant
# PID-exclusion filter, which only trims an already-matched set.
# ---------------------------------------------------------------------------


def test_empty_env_var_yields_zero_survivors_not_wildcard_match():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    # The old, insufficient framing ("the PID exclusion filter below still
    # holds on its own") must no longer be the sole safety claim for an
    # empty/unset env var. It described PID exclusion as the fallback, but
    # PID exclusion does nothing to stop an unscoped wildcard from matching
    # unrelated processes in the first place.
    assert "the PID exclusion filter below still holds on its own" not in td, (
        "the misleading 'PID exclusion filter still holds on its own' "
        "framing must be replaced by the explicit zero-survivors fail-safe"
    )

    # The correct guarantee must be stated: empty/unset env var => zero
    # survivors, full stop.
    assert re.search(
        r"empty.{0,20}(or|/)\s*unset.{0,200}zero\s+survivors|"
        r"zero\s+survivors.{0,200}empty.{0,20}(or|/)\s*unset",
        td, re.IGNORECASE | re.DOTALL,
    ), (
        "Teardown must explicitly state that an empty/unset AAD_WORKTREE "
        "yields zero survivors, full stop"
    )

    # Windows B2-match: an explicit non-empty/set guard must precede the
    # wildcard match expression, short-circuiting to an empty survivor set.
    assert re.search(
        r"IsNullOrEmpty\(\$env:AAD_WORKTREE\)", td,
    ), (
        "the Windows B2-match recipe must explicitly guard on "
        "$env:AAD_WORKTREE being non-empty/set before evaluating the "
        "wildcard match, e.g. via [string]::IsNullOrEmpty"
    )
    assert re.search(r"\$survivors\s*=\s*@\(\)", td), (
        "the Windows B2-match recipe must short-circuit to an empty "
        "survivor set ($survivors = @()) when the env var is empty/unset"
    )

    # POSIX B2-match: an equivalent explicit guard.
    assert re.search(r'-z\s+"\$AAD_WORKTREE"', td), (
        "the POSIX B2-match recipe must explicitly guard on $AAD_WORKTREE "
        "being non-empty/set (e.g. `[ -z \"$AAD_WORKTREE\" ]`) before "
        "evaluating pgrep -f, short-circuiting to an empty candidate set "
        "when it is empty/unset"
    )

    # Both OSes' degradation failure modes must be named explicitly, so the
    # fail-safe's rationale is documented, not just asserted.
    assert re.search(r'-like\s+"\*\*"', td), (
        "Teardown must explicitly name the Windows degradation failure "
        "mode: an empty AAD_WORKTREE turns the match into -like \"**\", "
        "which matches every process"
    )
    assert re.search(r'pgrep -f\s+""', td), (
        "Teardown must explicitly name the POSIX degradation failure mode: "
        "an empty AAD_WORKTREE turns the match into pgrep -f \"\", which "
        "matches every process on the system"
    )


# ---------------------------------------------------------------------------
# BR10 (round 7, Codex finding 2) — pgrep -f treats its argument as an
# extended regular expression, not a literal substring. A worktree path
# containing an ERE metacharacter (. [ ] * ^ $ ( ) { } ? + | \) can overmatch
# unrelated processes or fail to match the worktree's own processes. The
# POSIX B2-match recipe must regex-escape the path before ever passing it to
# pgrep -f.
# ---------------------------------------------------------------------------


def test_posix_pgrep_pattern_is_regex_escaped():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert re.search(r"extended regular expression|\bERE\b", td, re.IGNORECASE), (
        "Teardown must explain that pgrep -f treats its argument as an ERE, "
        "not a literal substring"
    )
    assert "escaped_worktree" in td, (
        "Teardown must introduce an escaped variable before the worktree "
        "path is ever passed to pgrep -f"
    )
    assert "escaped_worktree=$(printf '%s' \"$AAD_WORKTREE\" | sed" in td, (
        "Teardown must document the sed-based ERE-escaping recipe applied "
        "to $AAD_WORKTREE before it feeds pgrep -f"
    )
    # Scope the pgrep-invocation assertion to the ACTUAL fenced POSIX
    # recipe, not the prose paragraph that merely describes it in different
    # words. The prose sentence ("enumerate candidates via `pgrep -f
    # "$escaped_worktree"`, ... falling back to `pgrep -f "$escaped_worktree"`
    # alone where `/proc` is unavailable") never appears verbatim in the
    # real fenced code, which reads `candidates=$(pgrep -f
    # "$escaped_worktree" || true)` (the `=$(` command-substitution form,
    # no space, plus the ticket #86-round-3 `|| true` fallback so a
    # no-match exit code never propagates). Checking only the prose would
    # let this test keep passing even if the fenced snippet regressed to
    # unescaped $AAD_WORKTREE.
    sh_block = _extract_sh_fence(td)
    assert 'candidates=$(pgrep -f "$escaped_worktree" || true)' in sh_block, (
        "the POSIX B2-match recipe's fenced code must enumerate candidates "
        "via pgrep -f on the ESCAPED variable (not the raw, unescaped "
        "$AAD_WORKTREE), with an explicit `|| true` so pgrep's no-match "
        "exit code (1) never propagates"
    )


# ---------------------------------------------------------------------------
# BR11 (round 7, Codex finding 2) — PowerShell's -like treats *, ?, [, ] as
# wildcard metacharacters. * and ? cannot appear in a legal Windows path, but
# [ and ] can, and an unescaped bracket pair silently narrows the match to a
# single-char class instead of the literal text, causing the Windows
# B2-match recipe to FAIL to find a genuinely matching survivor process.
# ---------------------------------------------------------------------------


def test_windows_like_pattern_is_wildcard_escaped():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert "[System.Management.Automation.WildcardPattern]::Escape(" in td, (
        "the Windows B2-match recipe must escape the worktree path via the "
        "built-in WildcardPattern.Escape() before building the -like "
        "pattern, since -like treats [ and ] (legal Windows path "
        "characters) as wildcard metacharacters"
    )
    assert "$escapedWorktree = [System.Management.Automation.WildcardPattern]::Escape($env:AAD_WORKTREE)" in td, (
        "the escape call must be applied to $env:AAD_WORKTREE and assigned "
        "before the -like match runs"
    )
    assert '$_.CommandLine -like "*$escapedWorktree*"' in td, (
        "the Windows B2-match -like expression must match against the "
        "ESCAPED variable, not the raw, unescaped $env:AAD_WORKTREE"
    )


# ---------------------------------------------------------------------------
# BR12 (round 7, Codex finding 1) — env-var indirection is not a "second,
# independent layer" against self-matching; it is a prose-accuracy fix, not
# a new behavioural requirement. PID-based self/ancestor/descendant
# exclusion is the load-bearing protection against a single-invocation
# self-match (assignment + match issued as one shell invocation, e.g. one
# `powershell -Command "..."` / `sh -c "..."` string) — a scenario in which
# the wrapping process's own command line still carries the literal
# worktree path regardless of how many logical statements the script
# contains. This is a documentation-accuracy assertion only.
# ---------------------------------------------------------------------------


def test_env_var_indirection_not_framed_as_second_independent_layer():
    skill_body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(skill_body)
    agents = _read(AGENTS_MD)

    # The misleading framing must be gone from both files (it is checked
    # word-adjacently since the prose may legitimately wrap across lines
    # elsewhere in the file, but the exact phrase itself must not appear).
    assert "as a second, independent" not in skill_body, (
        "SKILL.md must not frame env-var indirection as 'a second, "
        "independent layer' against self-matching"
    )
    assert "as a second, independent" not in agents, (
        "AGENTS.md must not frame env-var indirection as 'a second, "
        "independent layer' against self-matching"
    )

    # The corrected, load-bearing claim must be present in both files.
    assert re.search(
        r"PID-exclusion is the\s*\n?\s*load-bearing protection against the "
        r"single-invocation self-match", td,
    ), (
        "SKILL.md's Teardown must state that PID-exclusion is the "
        "load-bearing protection against the single-invocation self-match "
        "scenario"
    )
    assert re.search(
        r"PID-exclusion is the\s*\n?\s*load-bearing protection against the "
        r"single-invocation self-match", agents,
    ), (
        "AGENTS.md must state that PID-exclusion is the load-bearing "
        "protection against the single-invocation self-match scenario"
    )


# ---------------------------------------------------------------------------
# BR-A1 (self-found, same bug class as #86) — exclusion is evaluated per
# candidate at match time, never as a pre-match snapshot subtraction. A
# snapshot taken before B2-match's own pipeline runs (e.g. before
# `candidates=$(pgrep -f "$escaped_worktree")` forks its command-substitution
# subshell) cannot contain a process that pipeline forks afterward, so only a
# per-candidate, live ancestor-chain walk closes the gap.
# ---------------------------------------------------------------------------


def test_exclusion_is_evaluated_per_candidate_not_a_prematch_snapshot():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    n = _normalize(td)

    assert re.search(r"per candidate", td, re.IGNORECASE), (
        "Teardown must state exclusion is evaluated per candidate"
    )
    assert re.search(
        r"precomputed once and subtracted|pre-match snapshot",
        td, re.IGNORECASE,
    ), (
        "Teardown must explicitly reject a pre-match/precomputed-once "
        "snapshot subtraction as insufficient"
    )
    assert re.search(r"subshell", td, re.IGNORECASE), (
        "Teardown must name the matcher's own forked subshell (e.g. the "
        "pgrep command-substitution) as the case a pre-match snapshot misses"
    )
    assert re.search(r"forks.{0,80}after.{0,40}snapshot", n, re.IGNORECASE), (
        "Teardown must explain that a snapshot cannot contain a process the "
        "matcher's own pipeline forks after the snapshot was taken"
    )


# ---------------------------------------------------------------------------
# BR-A2 (self-found) — the /proc/<pid>/cwd match requires a path BOUNDARY
# (equal to $AAD_WORKTREE, or prefixed by it followed by a path separator),
# not a bare prefix match, which would wrongly pull in a sibling worktree
# directory whose path merely starts with this one's (e.g. a retry-suffixed
# worktree this plugin's own B3 fallback recommends on a name collision).
# ---------------------------------------------------------------------------


def test_proc_cwd_match_requires_path_boundary():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    n = _normalize(td)

    assert re.search(
        r"equal to.{0,40}\$AAD_WORKTREE.{0,120}prefixed by.{0,40}"
        r"\$AAD_WORKTREE.{0,60}path separator",
        n, re.IGNORECASE,
    ), (
        "Teardown's /proc/<pid>/cwd match must require the cwd be equal to "
        "$AAD_WORKTREE, or prefixed by it followed by a path separator — "
        "not a bare prefix match"
    )
    assert re.search(r"575f0fcb-retry|sibling worktree", n, re.IGNORECASE), (
        "Teardown must name the sibling-path overmatch scenario (e.g. a "
        "retry-suffixed worktree directory) that a bare prefix match would "
        "wrongly pull in"
    )


# ---------------------------------------------------------------------------
# BR-A3 (self-found) — the POSIX empty/unset AAD_WORKTREE guard is a real
# `if`/`else`/`fi` short-circuit, not a fragment (`[ -z "$AAD_WORKTREE" ] &&
# survivors=""`) that leaves the following pgrep call running unconditionally
# regardless of the guard.
# ---------------------------------------------------------------------------


def test_posix_empty_env_guard_is_a_real_short_circuit():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    m = re.search(r"```sh\s*\n(.*?)```", td, re.DOTALL)
    assert m, "Teardown must contain a fenced ```sh``` block for the POSIX guard"
    block = m.group(1)

    assert re.search(
        r'if\s*\[\s*-z\s*"\$AAD_WORKTREE"\s*\]\s*;\s*then', block
    ), "the guard must be a real `if [ -z \"$AAD_WORKTREE\" ]; then` statement"
    assert re.search(r"\belse\b", block), "the guard must have an else arm"
    assert re.search(r"\bfi\b", block), "the guard's if block must be closed with fi"
    assert "candidates=$(pgrep" in block, (
        "the pgrep candidate enumeration must appear inside the fenced "
        "if/else block"
    )

    else_idx = re.search(r"\belse\b", block).start()
    outer_fi_idx = block.rindex("fi")
    pgrep_call_idx = block.index("candidates=$(pgrep")
    assert else_idx < pgrep_call_idx < outer_fi_idx, (
        "the pgrep call must be INSIDE the else arm — the empty/unset case "
        "must short-circuit before pgrep ever runs, not merely assign an "
        "empty result and then run pgrep unconditionally afterward"
    )


# ---------------------------------------------------------------------------
# BR-A4 (self-found) — the Windows self/ancestor/descendant exclusion walk is
# concrete, deriving its pid->ParentProcessId lookup from the same
# Get-CimInstance Win32_Process snapshot already captured for matching — not
# a placeholder (`<ancestor-chain-PIDs>` / `<descendant-tree-PIDs>`).
# ---------------------------------------------------------------------------


def test_windows_exclusion_walk_is_concrete_not_placeholder():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)

    assert "Get-CimInstance Win32_Process" in td
    assert "ParentProcessId" in td
    assert "$parentOf" in td, (
        "the Windows recipe must build a concrete pid->ParentProcessId "
        "lookup (e.g. $parentOf), not a placeholder"
    )
    assert re.search(r"\$parentOf\[.{0,40}\]\s*=\s*.{0,10}ParentProcessId", td), (
        "the $parentOf map must be derived from the ParentProcessId field "
        "of the same Get-CimInstance Win32_Process snapshot used to match"
    )
    assert "<ancestor-chain-PIDs>" not in td, (
        "the placeholder '<ancestor-chain-PIDs>' must no longer appear in "
        "the Windows recipe"
    )
    assert "<descendant-tree-PIDs>" not in td, (
        "the placeholder '<descendant-tree-PIDs>' must no longer appear in "
        "the Windows recipe"
    )


# ---------------------------------------------------------------------------
# BR-A5 (self-found) — POSIX B2-kill rechecks liveness (kill -0) between
# kill -TERM and kill -KILL, with a brief in-shell grace period, explicitly
# distinguished from a long-running foreground wait (ticket #88: the former
# ~15-minute B6 liveness wait this used to be contrasted with is gone, but
# the distinction from ANY long-running foreground wait must survive).
# ---------------------------------------------------------------------------


def test_posix_kill_rechecks_liveness_between_term_and_kill():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    n = _normalize(td)

    term_idx = td.index("kill -TERM")
    zero_idx = td.index("kill -0")
    kill_idx = td.index("kill -KILL")
    assert term_idx < zero_idx < kill_idx, (
        "POSIX B2-kill must recheck liveness (kill -0) strictly between "
        "kill -TERM and kill -KILL"
    )
    assert re.search(
        r"not.{0,20}a\s+long-running\s+foreground\s+wait",
        n, re.IGNORECASE,
    ), (
        "Teardown must explicitly distinguish this brief in-shell grace "
        "from a long-running foreground wait, so a future reader doesn't "
        "conflate the two"
    )
    assert not re.search(r"~?15.minute\s+B6\s+liveness\s+wait", n, re.IGNORECASE), (
        "Teardown must no longer contrast this grace period against the "
        "removed B6 liveness wait specifically — ticket #88 removed it"
    )


# ---------------------------------------------------------------------------
# Cross-file mirror — AGENTS.md carries the substance of BR-A1 (per-candidate
# exclusion, not a pre-match snapshot) and BR-A2 (cwd path-boundary,
# sibling-path overmatch case).
# ---------------------------------------------------------------------------


def test_agents_md_mirrors_per_candidate_exclusion_and_cwd_boundary():
    agents = _read(AGENTS_MD)
    n = _normalize(agents)

    assert re.search(r"per candidate", n, re.IGNORECASE), (
        "AGENTS.md must mirror the per-candidate exclusion substance (BR-A1)"
    )
    assert re.search(r"precomputed once and subtracted", n, re.IGNORECASE), (
        "AGENTS.md must mirror the 'not a pre-match snapshot subtraction' "
        "substance (BR-A1)"
    )
    assert re.search(r"575f0fcb-retry|path separator", n, re.IGNORECASE), (
        "AGENTS.md must mirror the cwd path-boundary substance (BR-A2)"
    )


# ---------------------------------------------------------------------------
# BR13 (ticket #88, reviewer fix round 2, finding 1) — Teardown's B2-match
# Windows section must not frame its sequential-dispatch guarantee as
# "concurrent probes across wave members ... each target a distinct worktree
# path". That sentence describes the removed B6 concurrent-liveness-probe
# mechanism as still active. Since ticket #88 made wave-member dispatch
# sequential (Phase C runs one fresh synchronous spawn at a time, never
# parallel/named spawns), there are no "concurrent probes" any more — B2-
# match's teardown sweep only ever runs once per worktree, one invocation at
# a time.
# ---------------------------------------------------------------------------


def test_b2_match_teardown_does_not_frame_concurrent_probes_as_current():
    body = _extract_body(_read(ORCHESTRATE_MD))
    td = _extract_teardown(body)
    n = _normalize(td)

    assert "concurrent probes across wave members" not in n, (
        "Teardown's B2-match Windows section must not describe the removed "
        "B6 concurrent-liveness-probe mechanism ('concurrent probes across "
        "wave members') as still active — ticket #88 made wave-member "
        "dispatch sequential"
    )
    assert re.search(
        r"one\s+worktree\s+path\s+per\s+invocation|sequential",
        n, re.IGNORECASE,
    ), (
        "Teardown must instead plainly state that B2-match's teardown sweep "
        "only ever targets one worktree path per invocation, because "
        "dispatch is sequential now"
    )


# ---------------------------------------------------------------------------
# BR14 (ticket #88, reviewer fix round 2, finding 2) — AGENTS.md's B2-match
# self-match-prevention correction note must cite the CURRENT nohup+Monitor
# example (Phase C step 5's integration-gate run, `<detected-test-cmd>`), not
# the removed B6 bounded-wait's `<probe-loop>` example. SKILL.md's equivalent
# sentence was already fixed in a prior round; this AGENTS.md sentence was
# missed.
# ---------------------------------------------------------------------------


def test_agents_md_probe_loop_example_updated_to_detected_test_cmd():
    agents = _read(AGENTS_MD)

    assert "<probe-loop>" not in agents, (
        "AGENTS.md must no longer reference the removed B6 bounded-wait's "
        "<probe-loop> example"
    )
    assert "nohup <detected-test-cmd> > <log> 2>&1 &" in agents, (
        "AGENTS.md's B2-match self-match-prevention correction note must "
        "cite the current nohup+Monitor example, "
        "'nohup <detected-test-cmd> > <log> 2>&1 &' (Phase C step 5's "
        "integration-gate run), matching SKILL.md's already-fixed sentence"
    )
