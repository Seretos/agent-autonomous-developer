# agent-autonomous-developer — architecture notes

Pure skill + agents plugin (no binary, no MCP). Drives a ticket→draft-PR workflow for
projects in **any language** (stack auto-detected) on top of the `agent-project-issues`
and `agent-worktree` MCPs.

README.md covers *what* it does, install, and release. The skills/agents document their own
rules. This file records only the non-obvious decisions a contributor must not silently break
— the cross-file invariants and rationale you can't reconstruct from any single file.

## Tool priority

Skills and MCP tools take priority over raw file tools — and this **explicitly overrides** the generic harness default that says "prefer the dedicated file/search tools (Glob/Grep/Read)". When a skill or MCP tool covers the task, reach for it first; fall back to raw Glob/Grep/Read only when none applies.

Concretely: any *"where is X defined / what does the code support / which Y exist / how does X work / find the callers of X"* question is a **code-understanding task → use the matching skill first** (e.g. the `serena-wrapper` symbol-aware tools), never raw Glob/Grep/Read.

## Dispatcher-guard invariant (cross-file)

Lane detection is now centralized in a single thin `dispatch` skill. Both `orchestrate-tickets`
and `process-ticket` carry `disable-model-invocation: true` — neither is auto-selected by the
model. The dispatcher runs `git rev-parse --git-dir` vs `--git-common-dir`, compares the
outputs, and calls the appropriate backing skill.

The branch+worktree guard inside `process-ticket`'s Preconditions 2 is now defense-in-depth
(a backstop for power-user direct invocation), not the primary gate. The `orchestrate-tickets`
lane guard (Preconditions 1) likewise remains as a backstop.

**Invariant for contributors:** if you change the dispatcher's lane check logic, verify both
backing skills still receive the correct invocation arguments. The "change one guard, update
the other" rule no longer applies — there is only one guard.

## Developer and reviewer tool boundaries (denylist, not allowlist)

The `developer` and `reviewer` agents enforce their safety constraints via a
`disallowedTools:` **denylist** in their frontmatter — not a `tools:` allowlist.
This means both agents inherit whatever MCP tools are connected in the session
(Unity tools, future MCP servers, etc.) while still being blocked from the
operations they must never do.

**Why denylist?** An allowlist required enumerating every tool the agent would
legitimately need — including future MCP servers the plugin author can't predict.
A denylist lists only the small, stable set of *forbidden* operations, and new
MCP tools are available automatically.

**Developer denylist invariant.** The developer's `disallowedTools:` must block:
all PR operations (`create_pr`, `merge_pr`), all ticket-mutation operations
(`add_comment`, `update_ticket`, `create_ticket`, `delete_ticket`), and
worktree lifecycle operations that belong to the orchestrator (`worktree_create`,
`worktree_remove`, `worktree_switch`). `worktree_start` is deliberately NOT
denied — the developer needs it for the long-lived-process guardrail.

**Reviewer denylist invariant.** The reviewer is strictly read-only. Its
`disallowedTools:` must additionally block all file-write tools (`Edit`, `Write`,
`NotebookEdit`) and all Serena write tools (`replace_symbol_body`,
`insert_after_symbol`, `insert_before_symbol`, `rename_symbol`, `replace_content`,
`safe_delete_symbol`). The reviewer also denies `worktree_start` — it has no
reason to launch processes.

**Known fragility.** When a new MCP server with write tools is connected to a
session, those write tools are available to both agents by default. If the new
server has write operations that the reviewer (or developer) must not use, add
them to the respective `disallowedTools:` list. The agents' Hard Rules remain
the behavioral backstop, but the denylist is the primary enforcement mechanism.

## Wave-based fleet orchestration + integration branch (cross-file)

`orchestrate-tickets` runs as a **wave-based fleet** over a single shared
**integration branch** (`integration/<run-slug>`, created off the refreshed
`base` at run start and pushed once), not a one-worktree-per-ticket-then-stop
model. The `conflict-analyst` lays the selected tickets out into an ordered
`waves` array (DAG-layered parallel-safe sets) instead of a single flat
`parallel` set; `orchestrate-tickets` iterates `waves` in order. Per wave: its
worktrees branch off the **current integration-branch head** (not `base`
directly — only the integration branch itself branches off `base`);
`process-ticket` runs per member in `mode=integration`; a B4 clean-checkout
gate runs before merging; approved-and-green members are merged `--no-ff`
into the integration branch; a full-suite **integration gate** runs on the
result. On GREEN, the wave's worktrees are torn down and the integration
branch is **pushed before the next wave creates any worktree (B1)** — a
hard precondition, never skipped. On RED, the run **STOPs immediately with no
automatic revert**: the failed wave's merge commits stay local/unpushed, its
worktrees stay intact for inspection, and already-pushed prior waves are never
rewound — resolution is the user's call. At the end of the run, exactly
**one** combined draft PR is opened (`head=<integration-branch>`) with
`Closes #<n>` for every processed ticket, followed by one link-comment per
ticket.

This is the concrete implementation of the isolated-worker model described in
"Why ticket-slicing knowledge lives in the orchestrator, not a standalone
skill" below — the `process-ticket` `mode` parameter (`solo` default vs.
`integration`, orchestrator-invoked) is the single-pipeline mechanism that
lets the same skill serve both a manually-driven single worktree and a
wave-orchestrated fleet member without forking the pipeline: `solo` keeps
today's own-push/own-PR/own-comment behaviour; `integration` runs the
identical Phase 1-4 and local commit but yields push/PR/comment to the
caller, because the caller is merging multiple members into one shared
branch and opening one combined PR, not one per ticket.

**Invariant for contributors:** if you change the wave loop's merge, gate, or
push ordering in `skills/orchestrate-tickets/SKILL.md`, keep B1 (push before
next wave) and the RED no-auto-revert behavior intact — they are what makes a
pushed integration branch a safe, always-green base for the next wave to
build on.

**Sequential, unnamed wave-member dispatch replaces the report-loss fallback
(ticket #88 — supersedes the former "B6" safeguard).** Phase C used to drive
wave members **in parallel**, which necessarily meant each was a
background/named `Agent` spawn — the same delivery mechanism whose failure
mode caused the planner-spawn deadlock originally fixed in #58/#60. A live
incident (ticket #88) found this causing repeated silent report loss at the
wave-member level in one run: duplicate developer instances racing
concurrently in the same worktree, a report arriving at the wrong parent,
and — separately — a developer ending its turn without ever starting its
mandated test run. The self-healing apparatus that used to live here
(git-state plus result-marker-file verification, a status-check
`SendMessage` ping, bounded liveness probes, wedged-process detection)
compensated for that report loss after the fact, discovered only by manual
follow-up. Ticket #88 instead eliminates the precondition for it rather than
compensating further: Phase C now drives wave members **sequentially**, one
fresh synchronous unnamed spawn at a time — the same pattern
`process-ticket`'s own Phase 2-4 already use for the planner/developer/
reviewer — so there is never more than one open dispatch, never an
ambiguous report recipient, and never a reason to `SendMessage` a running
dispatch instead of waiting for its one synchronous reply. A member is
merged when its own synchronous report shows `APPROVE` and `PASS` — read
directly off that reply; no git-state/marker-file cross-check is needed or
performed any more. `process-ticket` also now posts a short status comment
to the ticket after Phase 3 (test result) and Phase 4 (review verdict), in
addition to its existing Phase 2 plan comment, so a ticket carries a durable
trail of how far a run got even if the session driving the pipeline dies
mid-run — see `skills/process-ticket/SKILL.md`'s Phase 3/4 notes. The
result-marker file (`.process-ticket-result.json`) and its report's
`final: true` field are unaffected by this change — `process-ticket` still
writes both unconditionally, in both modes (see "Target-repo `.gitignore`"
below) — only the `orchestrate-tickets`-side *reader* that used to consume
them for the report-loss fallback is gone.

**Target-repo `.gitignore`, not this plugin's (finding from ticket #64 round
2; ordering corrected in round 3).** `process-ticket` always runs against an
arbitrary **target project repo** (supplied via `project_id`/`worktree_path`
— see "Why the project id is always a parameter" above), never "this plugin
repo itself." This plugin's own `.gitignore` entry for
`.process-ticket-result.json` has zero effect on real usage — it only helps
when testing this plugin against its own repo. The actual fix lives in
`skills/process-ticket/SKILL.md`'s Final step 1 (both modes), which now runs
**before** step 2's commit: it checks whether the **target repo's own**
`.gitignore` already contains the line `.process-ticket-result.json` and
appends it (idempotent, one line, untouched otherwise) if not, and only
*then* does step 2 run `git add -A` and commit. Running the check before the
commit (not after, as round 2's fix originally had it) means that when an
append is needed, it is staged and committed as part of *this run's own*
commit — properly attributed to the ticket that first needed it, not left as
an uncommitted stray change for a later, unrelated ticket's `git add -A` to
silently sweep up unattributed. It also protects every subsequent
`process-ticket` run against that same worktree/repo — by the time a later
run reaches its own step 1, `.gitignore` already excludes the marker, so that
later run's own `git add -A` correctly skips the still-untracked, now-ignored
marker file left over from this run. The marker write itself (step 6) still
happens after the commit, unchanged — only the `.gitignore` check/append
moved earlier. One more consequence of the corrected ordering: because the
marker is gitignored *before* it's written, `git status --porcelain` in the
worktree shows **no entry at all** for it (a gitignored untracked file
produces no `??` line) — harmless either way, since nothing in
`orchestrate-tickets` reads worktree `status --porcelain` output looking for
this marker any more (see the wave-member dispatch note above).

**B5 — developer working-directory/Serena-project safeguard (distinct from
B4).** `agents/developer.md` documents a **B5** safeguard — verifying the
working directory (`git -C <worktree> rev-parse --show-toplevel`) and the
active Serena project match the intended worktree, both before the first
edit and again immediately before handing off for commit — so a silent
context mismatch can't ship a commit built in the wrong tree. This is
defense-in-depth against a stray session/cwd drift (a session reused across
an earlier ticket's worktree, or a background shell whose cwd silently
settled somewhere other than the worktree it was handed) — not a
simultaneous-access risk: ticket #88 made `orchestrate-tickets`' wave-member
dispatch sequential, one fresh spawn at a time, so `developer` subagents for
different wave members no longer run at the same time across different
worktrees under the wave model. **B5 is
deliberately a different label from B4** (this file's and
`skills/orchestrate-tickets/SKILL.md`'s wave-loop clean-checkout gate, above)
to avoid a naming collision between two unrelated safeguards that happen to
live in adjacent files.

## Every git invocation in orchestrate-tickets must be cwd-independent

Ticket #66: in background/job-mode invocations, the shell's cwd can be silently
reset between tool calls — potentially onto one of the fleet's own worker
worktrees. A plain, ambient-cwd git command (`git checkout <integration>`,
`git merge --no-ff <branch>`, `git status --porcelain`, `git push origin
<integration>`, …) can therefore be silently redirected into the wrong working
tree; a misdirected `git merge` in particular can report a bogus "Already up
to date." with no error, risking a combined PR that silently omits a ticket's
changes. Reproduced in a live run, not hypothetical.

Fix: every git invocation in `skills/orchestrate-tickets/SKILL.md` uses `git -C
<repo_root> …` — the same form Precondition 0's own guard already uses for its
`--git-dir`/`--git-common-dir` check. `repo_root` is bootstrapped once, via a
single ambient `git rev-parse --show-toplevel` call at the very top of
Preconditions, before Precondition 0's own guard runs (itself now `-C
<repo_root>`-pinned). That one bootstrap call is the sole intentional
exception — you cannot `-C` into a root you haven't discovered yet — and a
wrong resolution there is caught immediately by the guard it precedes. The one non-git, cwd-dependent step (the
Phase C integration-gate test run) is not a git command, so it instead opens
with an explicit `Set-Location <repo_root>` / `cd <repo_root>` as its first
statement — not a strategy mix, just the one place a location change is the
only option.

**Invariant for contributors:** any new git command added to
`orchestrate-tickets` (Preconditions, Phase C, Phase D, or Teardown) must be
written as `git -C <repo_root> …` from the start, never a bare/ambient form.
The single standing exception is the bootstrap `git rev-parse
--show-toplevel` call above. (Historical note: an earlier draft of this
section also carved out an exception for an "idle-fallback protocol"'s own
`git -C <worktree_path> …` commands — ticket #88 removed that protocol
entirely, along with every `-C <worktree_path>` git invocation in
`skills/orchestrate-tickets/SKILL.md`, so no such exception exists any
more.)

## Why the project id is always a parameter

agent-project-issues does not resolve cwd→project (`local_path` is null, `source: config`),
so there is no auto-detection to fall back on. Both skills take the project id as an explicit
argument and thread it through every subagent prompt and MCP call. Don't add a "guess the
project from cwd" shortcut — there's nothing to guess from.

## Stack auto-detection lives in the planner + developer

The plugin is language-agnostic. Stack assumptions are **detected from the project's config
files** (`pyproject.toml` → `python -m pytest`, `package.json` → `npm test`/`jest`/`vitest`,
`go.mod` → `go test`, `Cargo.toml` → `cargo test`, `pom.xml`/`build.gradle` → maven/gradle,
…) rather than hardcoded. The **planner** detects the stack and pins the concrete
test/install/build commands in the plan's test strategy; the **developer** executes *those*
commands (and re-derives them from the config if the plan is thin). Keep the orchestrating
skills stack-neutral — the scope stays in these two worker agents, in one place.

## Test adequacy is a three-agent chain

Tests aren't merely "written" — adequacy is enforced across three agents, and weakening any
one link drops the guarantee:

- **planner** mandates the strategy: a driving test per behavioural requirement (declaring its
  expected RED state), the edge cases as additional coverage, and a test for every behavioural
  change.
- **developer** performs TDD per behavioural requirement (the driving test red→green first,
  additional coverage may already pass) and reports structured evidence for what each asserts.
- **reviewer** makes coverage a **`[blocking]` gate** — a missing driving/regression test, an
  untested behavioural change, or an uncovered edge case is `CHANGES_REQUESTED`.

Enforcement rides the existing one-round fix loop in `process-ticket`: a blocking coverage
finding sends the developer back to add the test, then the reviewer re-checks. There is
deliberately **no separate test phase/agent** — test scope stays in these worker agents for
the same reason the stack-detection scope does (one place, not smeared across the skill).

**TDD tightening (all ticket types, red→green reporting).** The test-first mandate was
originally scoped to "for a bug/defect ticket, write a regression test first" — feature
tickets had no equivalent requirement. Both `developer` and `reviewer` now apply the same
red→green discipline to **every** ticket type: write the test first, confirm it fails against
the unfixed/pre-change code (red — a regression test for a bug, a new-behaviour test for a
feature), then confirm it passes after the change (green). The developer's change report must
show **both** runs, not just the final green one; the reviewer's test-coverage hard gate now
also checks for that red→green evidence and returns `CHANGES_REQUESTED` with a `[blocking]`
finding when it's missing — a final-green-only report no longer passes review.

**TDD granularity: per behavioural requirement, not per individual test (ticket #74 — a
granularity relaxation, distinct from the scope invariant above).** The tightening above is
about **scope** — which ticket types red→green applies to (bug AND feature, both) — and that
scope invariant is unchanged and must not be conflated with this note. This note is a separate
**granularity** axis: red→green is anchored to each **behavioural requirement**, not to every
individual new/extended test, because the per-test mandate pushed agents toward fabricating
artificial per-test failures instead of demonstrating the missing behaviour once. Concretely,
per behavioural requirement there is one **driving test** that must go red→green; **additional
coverage tests** for that requirement's edge cases may legitimately **already pass** — they
need not each manufacture their own failure. One shared vocabulary runs through all three
agents and this file: **Behaviour** / **Driving test** / **RED** / **GREEN** / **Additional
coverage**. The **planner** declares the *expected* RED state per behavioural requirement
(Behaviour / Driving test / Expected RED reason / Expected GREEN outcome / Additional
edge-case coverage); the **developer** *produces* the structured evidence (the same fields,
plus the RED/GREEN commands run and the Final suite result); the **reviewer** *validates* it
(driving test exists, RED failed for the expected reason, GREEN validates the behaviour, edge
cases covered) and must explicitly **not** require every additional coverage test to have been
red.

**Valid RED, defined once, shared verbatim.** A driving test's failure only counts as RED if
it fails because the behaviour is genuinely missing or wrong. Syntax errors, import failures,
missing dependencies, a broken environment, unrelated failing tests, and running from the
wrong working directory do **not** count as RED — they are bugs in the check itself, not
evidence of a missing behaviour, and must be fixed before RED is claimed.

**Non-behavioural changes are exempt.** Docs, formatting, comments, dependency bumps, build
config, and pure refactoring have no behaviour to drive red; pure refactoring instead must
preserve a **GREEN baseline** (the existing suite stays green throughout) rather than
manufacture an artificial RED.

**Retroactive tests and fix iterations.** A test written for behaviour the implementation
already had (predating the test) must be honestly disclosed as a retrospective regression
test — never a fabricated historical RED — and its protective value assessed going forward.
On a reviewer fix pass, the developer appends new TDD evidence for the fix; it does not
overwrite the evidence already reported for the prior round.

Baseline discipline carries over unchanged: run the relevant existing tests green before
writing the new driving test where practical, and prefer small RED→GREEN loops per
behavioural requirement over one big implement-then-test-everything pass.

## Optional Codex review augmentation lives in the reviewer

When the Codex plugin (`openai/codex-plugin-cc`) is installed and available, the `reviewer`
agent runs an **extra** Codex correctness pass and folds Codex's blocking findings into its
`VERDICT`. A few non-obvious decisions:

- **It lives in the `reviewer` agent, not in `process-ticket`.** The agent already owns the
  `VERDICT: APPROVE / CHANGES_REQUESTED` contract, so the skill and its one-round fix loop stay
  untouched — same as keeping stack scope in the worker agents.
- **Presence-driven, no flag.** Detection = glob the Codex companion script under
  `~/.claude/plugins/cache/<marketplace>/codex/<version>/scripts/codex-companion.mjs`; the
  reviewer gates on `codex.available` being `true` in `setup --json` (CLI + runtime
  installed), then attempts the pass and degrades on failure. A cold broker
  (`auth.loggedIn: false` but `auth.requiresOpenaiAuth` not `true`) is NOT treated as
  not-authenticated — the broker starts on-demand and the existing non-zero-exit degradation
  is the backstop. No opt-in setting.
- **Why a bundled script (`scripts/codex-review.mjs`), not a direct companion call.** The
  slash command `/codex:review` is `disable-model-invocation: true` (user-typed only) and
  subagents have no `Skill`/`Agent` tool. The old direct-companion paths (`adversarial-review
  --wait --base origin/<default-branch>` and `task --prompt-file` size-branching) were
  replaced by the bundled script because `adversarial-review` produces an empty diff in the
  App-Server sandbox on Windows with unstaged changes — silently skipping the review. The
  bundled script's `working-tree` mode runs `git add -A` then `git diff --staged` to collect
  the diff robustly before feeding it to Codex via `task --prompt-file` — platform-independent,
  works on Windows with unstaged changes. `--write` is never passed: Codex must stay
  review-only, like the reviewer.
- **Fragile bit.** The cross-plugin path discovery depends on the cache layout above; if the
  marketplace/plugin dir names change, discovery returns nothing and the reviewer **degrades
  silently** to its built-in review (never a hard error).
- **Teardown coupling (cross-file).** The Codex pass spawns an `app-server-broker.mjs` helper
  that is not a daemon-tracked job and is not stopped by worktree teardown automatically.
  `orchestrate-tickets` teardown must force-kill that broker **before**
  `worktree_remove`, or on Windows the worktree dir stays locked, the remove half-completes,
  and the agent-worktree MCP state desyncs into an unremovable phantom entry. If you change how
  the reviewer launches Codex (process name or `--cwd`), update the teardown matcher in
  `skills/orchestrate-tickets/SKILL.md` to match. **This sweep was generalized (B2)** beyond a
  single named process: teardown now kills **any process whose command-line or cwd references
  the worktree path**, explicitly naming the Codex broker (`app-server-broker.mjs`) alongside
  the Serena LSP chain (`node`/`uvx`/`uv`/`serena.exe`/`python.exe`) as known offenders, rather
  than relying on a narrow process-name allowlist that a future helper could silently evade.
  **Clarification (ticket #86): this "narrow process-name allowlist"
  phrasing describes B2 as a whole, not B2-kill's own exe-name/broker filter
  below.** B2-kill's exe-name allowlist (`node`/`uvx`/`uv`/`serena.exe`/
  `python.exe` + `app-server-broker.mjs`) is unchanged from the pre-#86
  baseline — ticket #86 only extracted this same pre-existing filter into an
  explicitly-labeled "B2-kill" stage (previously fused inline into the
  single B2 `Where-Object`); it did not narrow or widen which processes are
  eligible for killing. The tension between that allowlist and this
  paragraph's "rather than relying on a narrow process-name allowlist"
  wording predates #86 (it describes B2-match's own survivor-set matching,
  which is path-based and unfiltered, not the allowlist-filtered kill step)
  and is out of scope for this ticket.
  **B2-match / B2-kill split, self-exclusion, path indirection (ticket #86).**
  The matching logic itself is now a named, shared primitive, **B2-match**,
  split from the kill-only **B2-kill**, so the matching logic lives in
  exactly one place rather than being restated inline. B2-match now excludes
  the orchestrator's own PID plus its full
  ancestor and descendant lineage from the match result *before* anything
  is killed or counted toward liveness — without this, a probe/sweep whose
  own invocation embeds the literal worktree path as a substring could
  match itself, which is exactly how a genuinely dead worker was once
  misread as "alive" (a self-matched orchestrator shell, a self CPU delta,
  a PID that drifted between checks). **This exclusion is evaluated per
  candidate, not as a set precomputed once and subtracted afterward**: for
  each PID in the raw match result, B2-match walks that candidate's own
  parent-PID chain (`ParentProcessId`/`ppid`) upward and discards it if the
  chain reaches the orchestrator's own PID (`$PID`/`$$`) or one of its
  ancestors. A one-time precomputed snapshot cannot contain a process the
  matcher's own pipeline forks *after* that snapshot — most notably the
  `pgrep`-enumerating command substitution's own subshell in the single
  `sh -c "AAD_WORKTREE=…; …"` invocation form — so only a per-candidate,
  match-time walk closes that gap; see
  `skills/orchestrate-tickets/SKILL.md`'s Teardown B2-match section for the
  full recipe. B2-match also assigns
  the worktree path to an `AAD_WORKTREE` env var in a separate preceding
  statement, then matches against the variable rather than substituting the
  literal path directly into the match expression. **Correction (ticket
  #86): this is not a second, independent self-match-prevention layer.**
  An earlier version of this note claimed it was; that overstated it. When
  the assignment and the match are issued as **one single shell invocation**
  (a single `-Command`/`-c` string — the pattern this plugin uses elsewhere,
  e.g. the `nohup <detected-test-cmd> > <log> 2>&1 &` dispatch used by Phase
  C step 5's integration-gate run), the *wrapping*
  process's own command line is the entire script text, which still carries
  the literal worktree path baked into the assignment statement — a naive
  command-line substring/wildcard scan would still match that wrapping
  process against itself regardless of statement separation. What actually
  prevents this is the self/ancestor/descendant **PID-exclusion** described
  above: the wrapping process's own PID is `$PID`/`$$` inside the script it
  is currently executing, so it is always a member of the self-exclusion set
  computed before anything is matched or killed — PID-exclusion is the
  load-bearing protection against the single-invocation self-match scenario.
  Env-var indirection's real, distinct benefit is different: it avoids
  re-embedding/duplicating the literal (and potentially
  special-character-laden) worktree path directly inside the match
  expression text itself — one assignment, one source of truth, referenced
  by variable everywhere the match runs. See
  `skills/orchestrate-tickets/SKILL.md`'s Teardown B2-match section for the
  full correction. **Empty/unset env-var fail-safe.** If the env
  var doesn't persist between calls, B2-match must never fall through to an
  unscoped wildcard match (`-like "**"` on Windows, `pgrep -f ""` on POSIX
  both degrade to matching every process on the system) — both recipes now
  guard on the var being non-empty/set before evaluating the match
  expression, yielding zero survivors, full stop, when it is empty/unset.
  This guarantee is independent of, and not rescued by, the self/ancestor/
  descendant PID-exclusion filter, which only trims an already-matched set
  and does nothing to prevent an unscoped wildcard from matching in the
  first place. The POSIX half of
  B2-match replaced its old unfiltered `pkill`-by-path sweep with a
  `pgrep -f`-enumerated candidate set refined by a `/proc/<pid>/cwd`
  boundary-match (equal to the worktree path, or prefixed by it followed by
  a path separator — a bare prefix match would wrongly pull in a sibling
  worktree directory, e.g. one ending `...-575f0fcb` overmatching
  `...-575f0fcb-retry`) where `/proc` is available, falling back to
  `pgrep -f` alone otherwise. The per-candidate exclusion walk above sources
  its POSIX pid→`ppid` linkage the same way B2-match's own descendant
  discovery does: a `/proc/*/stat` forward walk on Linux, falling back to
  `ps -eo pid,ppid` output on macOS/BSD where `/proc` is unavailable.
  **Regex-escaping (ticket #86).** `pgrep -f`
  treats its argument as an extended regular expression, not a literal
  substring, and PowerShell's `-like` treats `*`, `?`, `[`, `]` as wildcard
  metacharacters — both matched against `$AAD_WORKTREE` as a raw string.
  Worktree paths can legally contain these characters, so both recipes now
  escape the path before matching: POSIX escapes ERE metacharacters via
  `sed` before passing the result to `pgrep -f`; Windows escapes wildcard
  metacharacters via
  `[System.Management.Automation.WildcardPattern]::Escape()` before
  building the `-like` pattern. See `skills/orchestrate-tickets/SKILL.md`'s
  Teardown B2-match section for the exact recipes.
  **Self-cwd-lock terminal case (#67).** When B2's sweep finds zero processes and
  `worktree_remove` still reports the dir locked/`Permission denied`, the holder isn't a
  foreign PID at all — it's the orchestrator's own background-job shell whose cwd silently
  sits inside the worktree (the same cwd-drift mechanism #66 fixed for git invocations).
  `skills/orchestrate-tickets/SKILL.md`'s Teardown handles this as detect-and-flag-only: no
  looping the B2 kill logic, no `cd`/`Set-Location` away, just record the path on the
  `manual-cleanup-needed` list surfaced in Phase D.

## Long-lived process guardrail (cross-file)

`agents/developer.md` carries the rule: before starting any process that does not exit on its
own (daemon, dev-server, watcher, GUI editor, etc.), the developer must use `worktree_start`
with an appropriate `start:` contract step so the process is tracked and killed automatically
on worktree teardown. When no suitable contract step exists and an ad-hoc launch is
unavoidable, the developer must emit an explicit warning in the change report that the process
will survive worktree teardown and must be terminated manually.

The rule is **generic and app-agnostic by design** — no concrete tool or application is named
as a prescriptive target. App-specific variants (e.g. how to handle a Unity GUI editor) belong
in wrapper projects such as `agent-unity-wrapper`, not in this plugin.

**Invariant for contributors:** if you change the developer's process-launch guidance, verify
that the updated rule still covers **both** branches — (1) the tracked-start path
(`worktree_start` + `start:` contract step) and (2) the manual-warning fallback for ad-hoc
launches — and update this note to stay consistent with the new wording.

**Second cross-file branch (ticket #83) — never end a turn on a backgrounded command.**
`agents/developer.md` and `agents/reviewer.md` both carry a Hard Rule forbidding ending a
turn while a command the agent itself backgrounded is still running — a `task-notification`
event for a backgrounded Bash command is delivered only to the main/orchestrator session,
never to the sub-agent that started it, so ending the turn does not suspend the agent, it
**terminates** it. The two sanctioned resolutions are (a) an in-turn `Monitor` wait on the
command's log file, or (b) an explicit blocked/in-progress status report handing the wait to
the parent. No-op yield commands (`true`, `exit 0`, `echo waiting`, `sleep` as a turn filler)
are named explicitly as a forbidden anti-pattern — they terminate the turn rather than
suspend it. **Invariant: full-suite runs always background, targeted runs may stay
foreground.** `agents/developer.md`'s "Run the suite" step documents that the **full-suite
run always** uses `nohup <detected-test-cmd> > <log> 2>&1 &` + an in-turn `Monitor` wait,
regardless of the suite's expected duration — there is no duration estimate to weigh and no
judgment call to make — while **targeted runs during a red→green loop** (a single test file,
`-x`, `-k`, a single package/spec) **may remain plain foreground `Bash` calls**. A later edit
must not quietly narrow this boundary: widening "always" to exempt slow-looking suites, or
narrowing the targeted-run carve-out, would reopen the ~10-minute tool-cliff stall this
ticket closes. `skills/orchestrate-tickets/SKILL.md`'s own Phase C step 5 integration
gate dog-foods this same nohup+Monitor pattern rather than exempting the orchestrator
from its own rule.

## Why ticket-slicing knowledge lives in the orchestrator, not a standalone skill

Slicing recommendations are **model-relative** — only meaningful for the isolated-worker
model that `orchestrate-tickets` implements. A recommendation like "merge tickets #3 and #7
into one vertical slice" is sound advice for this plugin's model (one worktree, one worker,
no shared context) but would be wrong advice for a future `autonomous-teams` shared-context
model, where workers share working memory and can therefore coordinate on horizontally-cut
tickets without reconvergence pain.

Splitting slicing into a standalone `slice-tickets` skill would decouple the recommendation
from the execution model it describes. Changes to the orchestration model would require
updating both files in lockstep — a coordination burden with no benefit, and a source of
stale guidance when one file is updated and the other isn't. The `conflict-analyst` is the
natural home for fit assessment because it already reads all tickets, grounds footprints in
code, and has full access to the dependency graph; fit assessment is a natural extension of
that analysis, not a separate concern.

A future `autonomous-teams` shared-context model would require different slicing heuristics
(horizontal cuts become viable; wave-width and cross-wave file sharing matter less). Those
heuristics belong with that model's orchestrator — not here — for the same reason: keeping
recommendation and model co-located makes both easier to keep correct.

There is deliberately **no standalone `slice-tickets` skill** in this plugin. Do not create
one.

## Phase B confirmation default-skips on clean runs (ticket #73)

`orchestrate-tickets` Phase B no longer presents its interactive
`AskUserQuestion` go-ahead gate unconditionally. It now default-skips that
gate on a **clean run** — SINGLE mode, or MULTI mode with `fit.verdict ==
"good"` AND `deferred` empty — so an unattended run doesn't stall on a
rubber-stamp confirmation with no real decision to make. There is no flag and
no persisted preference; the clean case simply proceeds.

The confirmation stays **mandatory** whenever a real decision exists:
`fit.verdict == "poor"` (the Fit Warning path) OR a non-empty `deferred`
list. Those two cases are never skipped, regardless of how the rest of the
run looks.

Even when the gate is skipped, Phase B still prints a plain, non-interactive
status message — the waves in order, each with its branch — so an attended
user always sees what the run did.

**Invariant for contributors:** if you change Phase B's confirm logic, keep
the clean-run condition exactly as above (SINGLE, or good-fit + empty
deferred) and keep both mandatory cases intact — widening the skip condition
to cover a poor-fit or non-empty-deferred run would silently remove the only
point at which a human can catch a bad slice or an unresolved dependency
before N worktrees are launched.

## Backlog board release gate (ticket #76)

`orchestrate-tickets` Phase A no longer hands the conflict-analyst *every*
open ticket unconditionally on the implicit "none"/"all open" MULTI path
(no ticket numbers given). Before spawning the analyst on that path only —
SINGLE mode and an explicit MULTI subset ("several") bypass this gate
entirely, since the human already picked those tickets by number — it calls
`list_board_columns(project_id)` to detect the project's board. No board
configured, or a board with no column literally named `Backlog` (exact/
full-token match, not substring), means zero behavior change: the filter is
skipped and every open ticket is still a candidate. Otherwise, open tickets
currently sitting in the `Backlog` column are dropped from the candidate set
**before the conflict-analyst runs** — filter-before-analyst ordering, so a
parked ticket is never even considered for a wave. If the filter would empty
the candidate set entirely, the run states so plainly and STOPs before the
analyst spawn — never an empty fleet.

Phase B surfaces any skipped tickets as their own distinct group — "N
tickets skipped — still in Backlog" — never merged into `deferred` (a
`deferred` entry was considered and set aside by the analyst; a backlog-skip
entry never reached the analyst at all). This is **surface-only**: it does
not force the interactive AskUserQuestion gate, and it adds no clause to the
existing clean-run predicate (SINGLE mode, or MULTI with `fit.verdict ==
"good"` AND `deferred` empty — unchanged). It is shown in whichever Phase B
message actually prints for the run — the non-interactive clean-run status
message, or the interactive mandatory-gate body — never both.

**Untriaged tickets (ticket #79 — no board Status at all).** The original
#76 gate only caught tickets explicitly parked in a column literally named
`Backlog`; it did not catch a ticket that has **no board Status/column value
at all** — created via `create_ticket` and never added to the board —
because `list_board_columns`-driven filtering by column name can't match a
value that was never set (`list_tickets(column="Backlog")` legitimately
returns `[]` for "no Status", since unset is not the same as "Backlog"; this
was root-caused as expected `agent-project-issues` MCP behavior, not a bug
there). Whenever a board is configured — with or without a column literally
named `Backlog` — the gate now also drops open tickets that were never
triaged onto the board (no board Status set) from the candidate set, the
same filter-before-analyst ordering as the `Backlog`-column drop. Only the
"no board configured" case is exempt: with no board there is no board Status
to key off, so the untriaged drop does not apply either — zero behavior
change, same as before. Phase B surfaces untriaged-dropped tickets in the
same display-only "N tickets skipped — still in Backlog" group as
`Backlog`-column tickets — the group label now covers both reasons, still
distinct from `deferred` and still surface-only.

**Read-only / #77 boundary.** This gate only reads board state
(`list_board_columns`) to decide which tickets become candidates; it never
moves a ticket between columns, comments, or otherwise mutates anything.
Sibling ticket #77 (a separate wave) owns the write side — do not fold that
scope in here.

**Invariant for contributors:** if you change this gate, keep the ordering
(board detection and filtering happen strictly before the conflict-analyst
spawn), keep the scope restriction (implicit "none"/"all open" path only —
SINGLE and explicit-subset MULTI must keep bypassing it), and keep Phase B's
backlog-skip group display-only and distinct from `deferred` — folding it
into the clean-run predicate or into `deferred` would silently change what a
"clean run" means or blur two structurally different reasons a ticket didn't
make the fleet. Keep the untriaged drop tied to "a board is configured",
independent of whether a literal `Backlog` column exists — narrowing it back
to only fire alongside a `Backlog` column would reopen the #79 gap.

## Board card movement (ticket #77)

This closes out the #76 section's dangling write-side boundary reference
above ("Sibling ticket #77 ... owns the write side"). `process-ticket`
best-effort moves the ticket's board card as it executes, gated on the same
`list_board_columns(project_id)` detection #76 introduced for its read/
filter side — exact/full-token column-name match; no board configured, or no
column literally matching the target phase's name, means that specific write
is skipped silently, same backward-compat semantics as #76. Writes use
`update_ticket(project_id, ticket_id, custom_fields={"Status": <column>})`.

**Phase → column mapping.** Phase 1 (context-extractor + planner begin)
moves the card to `Doing`; Phase 4 (reviewer invoked) moves it to `Review`;
a `CHANGES_REQUESTED` fix-loop re-dispatch moves it back to `Doing`, then to
`Review` again once the re-review runs.

**Review is terminal automated state.** Per the user's decision, `Review` is
the terminal automated state — there is no automated `Done` write anywhere.
`process-ticket`'s Phase 4 `Review` write is the last board write the skill
ever makes for a ticket (both `solo` and `integration` mode; the Final step
adds none), and `orchestrate-tickets`' Phase D likewise writes no completion
column. This supersedes any "Done" wording in the originating ticket body.

**Best-effort, never blocking — looser than #76.** Unlike #76's read-side
gate, which STOPs on an ambiguous `list_board_columns` error, ANY failure on
this write side — detection error, no matching target column, or a failed
`update_ticket` call — degrades to a logged warning and the pipeline
continues. A board-write failure must never STOP or block the ticket's real
work.

**Provider-agnostic.** This mapping relies solely on `list_board_columns` and
`update_ticket`, which already normalize the underlying board/column model
for the connected provider — never hardcode provider-specific column
semantics here.

**Invariant for contributors:** if you change this mapping, keep Review as
the terminal automated state (no automated `Done` write, in either
`process-ticket` or `orchestrate-tickets`) and keep the write side
best-effort/never-blocking — widening it to STOP-on-failure like #76's
read-side gate would risk a board hiccup blocking real ticket work.

## Provider-portability gotchas

The draft-PR flow assumes GitHub/GitLab conventions that are **not** portable to Azure DevOps
or Jira:

- `Closes #<n>` auto-linking in the PR body (Azure DevOps uses `AB#<n>`, Jira differs).
- Ticket status strings are provider-native — resolve them via `list_ticket_statuses` for the
  project, never hardcode.

Make both provider-aware before targeting another backend.

## Release payload must ship every `${CLAUDE_PLUGIN_ROOT}`-referenced file (ticket #81)

Root cause of ticket #81: `.github/workflows/release.yml`'s staging step copied `skills/`,
`agents/`, and `assets/` into the install tree, but not `scripts/` or `hooks/` — so
`agents/reviewer.md`'s Codex second-opinion pass, which invokes
`${CLAUDE_PLUGIN_ROOT}/scripts/codex-review.mjs`, silently hit its "script missing" fallback
on every marketplace install, and `hooks/hooks.json`'s MCP-availability failsafe was dead the
same way. This was a **packaging gap**, not a missing implementation — both files already
worked correctly once actually present.

**Invariant for contributors:** any runtime file referenced via `${CLAUDE_PLUGIN_ROOT}/...`
from an agent (`agents/*.md`), a skill (`skills/**/*.md` — not just `SKILL.md`; a skill can
legitimately carry supporting/progressive-disclosure Markdown alongside `SKILL.md`, and a
`${CLAUDE_PLUGIN_ROOT}/...` reference there breaks on install identically, so the checker
scans every Markdown file under `skills/`, not only the entry-point one), or a hook manifest
(`hooks/hooks.json`) **must** be staged by `release.yml`'s "Stage install tree and build
release zip" step. Don't rely on remembering this by hand — `tools/check_plugin_payload.py`
is a generic, fail-closed release-time gate: it scans those file kinds for
`${CLAUDE_PLUGIN_ROOT}/<path>` references, and a workflow step ("Verify referenced plugin
files are staged", positioned strictly after staging and strictly before the orphan-branch
push) runs it against the actual staged tree, aborting the release if any reference resolves
to a repo path but not a staged one. `ALLOWED_UNSHIPPED` in that module is the single
documented escape hatch for a reference that is legitimately not meant to ship — it lands
**empty**, and any future entry needs an inline justification comment; the gate has no other
opt-out.

**If you add a new directory of runtime files** (beyond `skills/`, `agents/`, `assets/`,
`scripts/`, `hooks/`) that an agent/skill/hook references via `${CLAUDE_PLUGIN_ROOT}`, add its
`mkdir -p`/`cp -a` lines to the staging step in the same change that introduces the reference —
the gate will catch a forgotten one, but landing both together avoids a red release run.
