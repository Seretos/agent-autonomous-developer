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

**B6 — idle-triggered report-loss fallback (distinct from B1-B5).** Phase C
drives wave members **in parallel**, which necessarily means each is a
background/named `Agent` spawn — the same delivery mechanism whose failure
mode caused the planner-spawn deadlock originally fixed in #58/#60 (naming an
`Agent()` call switches it to background/mailbox delivery, and the callee has
no `SendMessage` tool to push a reply back if that delivery silently drops).
Ticket #64 found the worker-level analogue one layer up: a wave member can
finish all its real work — local commit made, reviewer verdict `APPROVE` —
and still go idle without ever sending its mandated Final-step report,
leaving an otherwise-successful run looking stalled. Unlike the planner fix,
eliminating background/named spawns is not viable here because members must
run in parallel, so the fix is a **fallback**, not elimination: when a member
goes **idle** without having sent its report — the trigger, not a timer, the
orchestrator has none — Phase C verifies the member's real ending state
directly instead of relying on the self-report: `git -C <worktree_path>
log`/`status --porcelain` plus `rev-list --count <branch_point_sha>..HEAD` (>
0, proving HEAD is ahead of the wave's branch point — the integration-branch
head SHA this worktree was created from — not merely that a commit exists at
HEAD, which a worktree that never did any real work would also show) to
confirm a genuine local commit landed this run, **only after which** the
result-marker file `<worktree_path>/.process-ticket-result.json` (written
unconditionally by `process-ticket`'s Final step, in both `solo` and
`integration` mode) is read to recover the reviewer verdict and test result
that git alone can't. The marker is never trusted on its own: because a RED
wave deliberately leaves its worktrees intact for inspection (no
auto-revert), a worktree could in principle be reused or retried, and a
stale marker from an earlier attempt could otherwise be misread as
confirming this run. Two things tie the marker to *this* run before it's
trusted: (1) it is only read after the HEAD-ahead-of-branch-point check
above has already proven a genuine new commit landed this run, and (2) its
own `ticket` field must equal this wave member's actual ticket number — a
mismatch means the marker is stale (left over from a different ticket ever
processed in this worktree) and it is rejected, treated the same as a
missing marker. **Conservative non-merge rule:** a member that can't be
confirmed this way — HEAD not ahead of the branch point, marker missing/
unreadable, marker `ticket` not matching this member's actual ticket number,
marker `verdict` not `APPROVE`, or marker `test` not `PASS` — is not merged;
it rolls into a later wave, exactly like a `CHANGES_REQUESTED`/red member
today. Checking `verdict` alone is not sufficient: the ordinary
(non-fallback) merge criterion is `APPROVE` **with a green test run**, so the
fallback path must disqualify on `test` too, or it would be silently weaker
than the normal path.

**Cross-file consistency invariant.** The literal filename
`.process-ticket-result.json` must stay identical in both
`skills/process-ticket/SKILL.md` (the writer) and
`skills/orchestrate-tickets/SKILL.md` (the reader) — a rename in one without
the other silently breaks the B6 fallback.

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
produces no `??` line) — see `skills/orchestrate-tickets/SKILL.md`'s Phase C
fallback, which relies on this.

**B5 — developer working-directory/Serena-project safeguard (distinct from
B4).** Under wave-based parallel processing, several `developer` subagents can
run concurrently across different worktrees; `agents/developer.md` documents
a **B5** safeguard — verifying the working directory (`git -C <worktree>
rev-parse --show-toplevel`) and the active Serena project match the intended
worktree, both before the first edit and again immediately before handing off
for commit — so a silent context mismatch can't ship a commit built in the
wrong tree. **B5 is deliberately a different label from B4** (this file's and
`skills/orchestrate-tickets/SKILL.md`'s wave-loop clean-checkout gate, above)
to avoid a naming collision between two unrelated safeguards that happen to
live in adjacent files.

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

- **planner** mandates the strategy: a regression test that reproduces the reported problem,
  the edge cases, and a test for every behavioural change.
- **developer** writes them (the regression test red→green first) and reports what each asserts.
- **reviewer** makes coverage a **`[blocking]` gate** — a missing regression test, an untested
  behavioural change, or an uncovered edge case is `CHANGES_REQUESTED`.

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

## Provider-portability gotchas

The draft-PR flow assumes GitHub/GitLab conventions that are **not** portable to Azure DevOps
or Jira:

- `Closes #<n>` auto-linking in the PR body (Azure DevOps uses `AB#<n>`, Jira differs).
- Ticket status strings are provider-native — resolve them via `list_ticket_statuses` for the
  project, never hardcode.

Make both provider-aware before targeting another backend.
