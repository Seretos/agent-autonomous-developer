"""
Driving tests for ticket #107: release.yml tags the release at a
parent-less orphan commit and calls `gh release create --generate-notes`,
which has no history to walk — so the release body (and, since #97, the
marketplace PR's `## Changelog`) is empty.

Behavioural requirements (see the approved plan, .adev/107-2/plan.md):
  R1 - notes are generated from main's history between two src/<TAG> markers,
       never via --generate-notes/--notes-start-tag against the orphan tag.
  R2 - the pre-flight step fails before any side effect on each violated
       precondition, and permits the first-ever release.
  R3 - tools/prev_release_tag.py resolves the previous release tag with
       strict-semver ordering and the right scope exclusions; the workflow's
       validate-step regex accepts/rejects the same grammar as the module.
  R4 - a new "Push source tag" step pushes src/<TAG> unconditionally at
       MAIN_SHA, after build success and before the orphan push, and aborts
       on a remote default-branch tip mismatch.
  R5 - the changelog reaches the marketplace dispatch payload byte-exactly,
       losing exactly one trailing newline.
  R6 - the `changelog` key is omitted entirely from the dispatch payload
       when the release body is empty.

R4b/R7/R8 are declared `ci-evidence` and R9/R10 `none` in the plan's Test /
verification strategy -- no driving test exists for them here. R11
(existing-suite: tests/test_release_payload.py, tests/test_release_script_
packaging.py, tests/test_ci_runs_pytest.py) must keep passing unmodified;
this file does not touch those.

Shared harness (per the plan): parse release.yml with yaml.safe_load, select
a step by `name:`, assert its `run:` body contains no unresolved `${{ ... }}`
GitHub Actions expression (inputs are threaded via `env:` instead -- this is
production scaffolding, not new behaviour, and was applied to the three
existing tested steps as part of this phase so the shared harness can execute
them at all outside Actions), then execute the body under bash.

Stubbing `gh`/`curl`: NOT done via PATH-prepended executable files. Git for
Windows' bash unconditionally prioritises its own bundled /mingw64/bin and
/usr/bin ahead of anything else on PATH (confirmed empirically while writing
this harness -- a PATH-prepended stub directory containing a bare-named
"curl"/"git" file is silently shadowed by the real bundled binary, while a
"gh" stub happened to work only because no real `gh` ships there at all).
The portable, reliable fix is a bash **function** with the same name,
defined at the top of the executed script: a shell function always wins over
a PATH lookup for a bare command name, on every platform. `run_step()` takes
a `stub_functions` dict of {name: function-body} and prepends
`name() { <body> }` definitions ahead of the step's real run: body.

Bash resolves as `C:\\Program Files\\Git\\bin\\bash.exe` on Windows, else
`shutil.which("bash")`; missing bash/jq skips locally but raises under
ADEV_REQUIRE_SHELL_TOOLING=1.

Note on R3: `tools/prev_release_tag.py` does not exist yet (tests phase --
this is the one requirement whose designed RED *is* the module's absence,
per the plan: "Expected RED: ModuleNotFoundError: tools.prev_release_tag").
Every R3 test therefore imports it lazily, inside the test function, so a
missing module fails only those tests and not this whole file's collection.

Assumed public API for tools/prev_release_tag.py (not yet implemented; the
implement-phase developer should build to this contract, since these tests
pin it):
  - `previous_release_tag(candidate_tags: list[str], *, plugin_name: str,
     exclude_tag: str) -> str | None` -- pure resolution function.
  - `VERSION_RE: re.Pattern[str]` -- compiled strict-semver acceptance
     pattern (no build metadata, no leading zeros), shared grammar authority
     against which the workflow's own validate-step regex is checked.
  - `main(argv: list[str] | None) -> int` -- CLI reading candidate tags on
     stdin, printing the highest non-excluded `<plugin>--v*` tag or nothing.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"

REQUIRE_SHELL_TOOLING = os.environ.get("ADEV_REQUIRE_SHELL_TOOLING") == "1"


# ---------------------------------------------------------------------------
# Shared harness
# ---------------------------------------------------------------------------


def _resolve_bash() -> str | None:
    if sys.platform == "win32":
        candidate = r"C:\Program Files\Git\bin\bash.exe"
        return candidate if pathlib.Path(candidate).is_file() else None
    return shutil.which("bash")


def _resolve_jq() -> str | None:
    return shutil.which("jq")


BASH = _resolve_bash()
JQ = _resolve_jq()


def _require_tool(path: str | None, tool_name: str) -> None:
    if path is not None:
        return
    if REQUIRE_SHELL_TOOLING:
        raise RuntimeError(
            f"{tool_name} not available on PATH and ADEV_REQUIRE_SHELL_TOOLING=1"
        )
    pytest.skip(f"{tool_name} not available on this machine")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow_data() -> dict:
    return yaml.safe_load(_workflow_text())


def _release_steps() -> list[dict]:
    return _workflow_data()["jobs"]["release"]["steps"]


def _find_step(step_name: str) -> dict | None:
    for step in _release_steps():
        if step.get("name") == step_name:
            return step
    return None


def _step_index(step_name: str, steps: list[dict]) -> int | None:
    for i, step in enumerate(steps):
        if step.get("name") == step_name:
            return i
    return None


def run_step(
    step_name: str,
    *,
    env: dict,
    cwd: pathlib.Path,
    stub_functions: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Extract a release.yml step's run: body, assert it splices no
    unresolved GitHub Actions expression, and execute it under bash with
    `stub_functions` (name -> body) defined as shell functions ahead of the
    real body, and `env` merged over the current process environment."""
    _require_tool(BASH, "bash")
    step = _find_step(step_name)
    assert step is not None, (
        f"release.yml has no step named {step_name!r} -- expected for a "
        "requirement whose driving test is a step-lookup failure."
    )
    run_body = step.get("run")
    assert run_body is not None, f"step {step_name!r} has no run: body"
    assert "${{" not in run_body, (
        f"step {step_name!r} still splices a GitHub Actions expression "
        f"(${{ ... }}) directly into run: -- inputs must come from env: so "
        f"the body is executable outside Actions:\n{run_body}"
    )

    preamble = "\n".join(
        f"{name}() {{\n{body}\n}}\n" for name, body in (stub_functions or {}).items()
    )
    script_path = cwd / "_step.sh"
    script_path.write_text(preamble + "\n" + run_body, encoding="utf-8", newline="\n")

    full_env = dict(os.environ)
    full_env.update(env)

    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", str(script_path)],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
    )


# Generic gh stub function body: logs every invocation's argv
# (record-separated by \x1d, arg-separated by \x1e, so embedded spaces/
# newlines in any arg are safe) to $GH_STUB_LOG, then answers two request
# shapes the pre-flight/create-release steps make: `gh api <path>` existence
# checks (200 for anything listed in space-separated $GH_STUB_EXISTING_REFS,
# 404 -- i.e. `return 1` -- otherwise) and `gh release view ...` (prints
# $GH_STUB_BODY_FILE's contents, if set). Anything else (e.g. `gh release
# create ...`) is simply logged and succeeds. Uses `return`, never `exit` --
# this runs as a shell *function*, and `exit` would terminate the whole
# script, not just this one simulated invocation.
_GH_STUB_BODY = r"""
{ printf '%s\x1e' "$@"; printf '\x1d'; } >> "$GH_STUB_LOG"
case "$1" in
  api)
    path="$2"
    for existing in $GH_STUB_EXISTING_REFS; do
      if [ "$path" = "$existing" ]; then
        echo '{}'
        return 0
      fi
    done
    return 1
    ;;
  release)
    if [ "$2" = "view" ]; then
      if [ -n "${GH_STUB_BODY_FILE:-}" ] && [ -f "$GH_STUB_BODY_FILE" ]; then
        cat "$GH_STUB_BODY_FILE"
      fi
    fi
    return 0
    ;;
  *)
    return 0
    ;;
esac
"""

# Generic curl stub function body: records the argument immediately
# following "-d" (the JSON payload, verbatim, including any embedded
# newlines) to $CURL_STUB_PAYLOAD_FILE.
_CURL_STUB_BODY = r"""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-d" ]; then
    printf '%s' "$arg" > "$CURL_STUB_PAYLOAD_FILE"
  fi
  prev="$arg"
done
return 0
"""


# Generic git stub function body: logs every invocation's argv (same wire
# format as the gh stub above) to $GIT_STUB_LOG and always succeeds. Used by
# the R4 "Push source tag" tests to record push/tag argv without touching a
# real remote.
_GIT_LOG_STUB = r"""
{ printf '%s\x1e' "$@"; printf '\x1d'; } >> "$GIT_STUB_LOG"
return 0
"""

# git stub that logs every invocation's argv (same wire format as above) to
# $GIT_STUB_LOG *and then delegates to the real git binary* via `command
# git` (which bypasses this shell function, avoiding infinite recursion).
# Used where a step's own git reads (rev-parse, tag -l, --is-shallow-
# repository, ...) must keep working against the real fixture repo while the
# test still wants to assert on which git subcommands were invoked --
# e.g. proving no `git tag -d` / `git push :refs/tags/...` deletion happens.
_GIT_PASSTHROUGH_LOG_STUB = r"""
{ printf '%s\x1e' "$@"; printf '\x1d'; } >> "$GIT_STUB_LOG"
command git "$@"
"""

# gh stub for the R1 notes-generation step ("Create tag and GitHub
# Release"): a `gh api .../releases/generate-notes` call succeeds and prints
# $GH_STUB_NOTES_BODY to stdout, simulating the real API response filtered
# through `--jq .body`. Any other `gh api` call fails (404) -- there are no
# other gh api calls in this step's real body. `gh release create` (and
# anything else) is logged and always succeeds.
_GH_NOTES_STUB = r"""
{ printf '%s\x1e' "$@"; printf '\x1d'; } >> "$GH_STUB_LOG"
case "$1" in
  api)
    path="$2"
    case "$path" in
      *generate-notes*)
        printf '%s' "$GH_STUB_NOTES_BODY"
        return 0
        ;;
      *)
        return 1
        ;;
    esac
    ;;
  *)
    return 0
    ;;
esac
"""

# gh stub for the R4 "Push source tag" step: any `gh api` call whose path
# contains "heads/" is the remote default-branch-tip re-read
# (`git/ref/heads/$DEFAULT_BRANCH`) and answers with $GH_STUB_TIP_JSON; any
# other `gh api` call (e.g. an existence check a wrong implementation might
# make against src/$TAG) answers 200/"already exists" -- so the unconditional
# case proves the push happens even when an existence check would have said
# "already there", and the mismatch case proves the push is withheld purely
# on the tip comparison.
#
# Fixed from round 4 (test-critic MAJOR): real `gh api ... --jq <expr>`
# filters the JSON response through gh's embedded jq before printing it. The
# prior version of this stub ignored `--jq` entirely and always printed the
# raw JSON blob -- so a reasonable, plan-consistent implementation that reads
# the tip sha via `gh api .../heads/$DEFAULT_BRANCH --jq .object.sha`
# (mirroring the plan's own `--jq .body` usage for the notes step) would
# receive the whole `{"object": {"sha": "..."}}` blob instead of a bare sha
# and could never compare equal to $MAIN_SHA -- permanently blocking
# test_source_tag_push_is_unconditional's matching-tip case regardless of
# correctness. This version honors `--jq .object.sha` specifically (the one
# expression the real API response shape for a ref lookup makes natural),
# extracting the sha field with a plain string match rather than a real jq
# dependency, since the JSON shape here is entirely test-controlled via
# $GH_STUB_TIP_JSON. Any other --jq expression (or no --jq at all) still
# prints the raw JSON, unchanged from before.
_GH_PUSH_STEP_STUB = r"""
{ printf '%s\x1e' "$@"; printf '\x1d'; } >> "$GH_STUB_LOG"
case "$1" in
  api)
    path="$2"
    jqexpr=""
    prev_arg=""
    for arg in "$@"; do
      if [ "$prev_arg" = "--jq" ]; then
        jqexpr="$arg"
      fi
      prev_arg="$arg"
    done
    case "$path" in
      *heads/*)
        if [ "$jqexpr" = ".object.sha" ]; then
          printf '%s' "$GH_STUB_TIP_JSON" | sed -E 's/.*"sha"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/'
        else
          printf '%s' "$GH_STUB_TIP_JSON"
        fi
        return 0
        ;;
      *)
        echo '{}'
        return 0
        ;;
    esac
    ;;
  *)
    return 0
    ;;
esac
"""


def parse_gh_log(log_path: pathlib.Path) -> list[list[str]]:
    if not log_path.exists():
        return []
    raw = log_path.read_text(encoding="utf-8")
    invocations = [chunk for chunk in raw.split("\x1d") if chunk != ""]
    return [inv.split("\x1e")[:-1] for inv in invocations]  # drop trailing empty from final \x1e


def _parse_github_output(text: str) -> dict[str, str]:
    """Parse a simple (non-heredoc) $GITHUB_OUTPUT file into a dict. All
    values this suite exercises are single-line, so `key=value` per line is
    sufficient -- no need for the multiline `key<<EOF` form."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


def _f_flag_values(inv: list[str]) -> list[str]:
    """Extract the values passed via `-f key=value` in a `gh api` invocation
    argv list."""
    return [inv[i + 1] for i, arg in enumerate(inv) if arg == "-f" and i + 1 < len(inv)]


def _flag_value(inv: list[str], flag: str) -> str | None:
    """Extract the value immediately following a given flag (e.g.
    `--notes-file <path>`) in a recorded invocation's argv list."""
    for i, arg in enumerate(inv):
        if arg == flag and i + 1 < len(inv):
            return inv[i + 1]
    return None


def _write_plugin_json(root: pathlib.Path, *, name: str, description: str = "Test plugin") -> None:
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": name, "description": description}), encoding="utf-8"
    )


PLUGIN_NAME = "agent-autonomous-developer"


# ---------------------------------------------------------------------------
# R1 - notes come from main's history between the two src/* markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prev_tag_env,expect_previous_tag_name",
    [
        (f"{PLUGIN_NAME}--v1.0.0", True),
        ("", False),
    ],
    ids=["with-prev-tag", "no-prev-tag"],
)
def test_notes_generated_from_main_markers(tmp_path, prev_tag_env, expect_previous_tag_name):
    """
    Driving test for R1: the release step must call
    `gh api .../releases/generate-notes` with tag_name=src/$TAG,
    target_commitish=$MAIN_SHA, and previous_tag_name=src/$PREV_TAG (omitted
    entirely when PREV_TAG is empty -- the first-release case), then create
    the release at $ORPHAN_SHA with --notes-file -- never
    --generate-notes/--notes-start-tag against the orphan commit (which has
    no history to walk).

    Expected RED: the step still calls `gh release create ... --generate-notes`
    and never calls `gh api .../generate-notes` -- a logic gap, not an
    environment/import failure. (Fixed from round 2: the old filter
    `inv[:2] == ["api"]` compared a 2-element slice to a 1-element list and
    could never match a real `gh api <path>` invocation, making the
    assertion fail for a mechanical reason that would persist even after a
    correct implementation.)

    Fixed from round 3 (test-critic CRITICAL): the generic `gh` stub used by
    every other case in this file answers *every* unmatched `gh api <path>`
    call with exit 1 (both parametrized cases here set no existing refs),
    and `RUNNER_TEMP` was never set in the child env, while the plan's real
    step body is `gh api .../generate-notes ... --jq .body >
    "$RUNNER_TEMP/notes.md"`. Under `bash -e` that means *any* correct
    implementation would abort at the generate-notes line before
    `gh release create` ever ran -- no implementation, right or wrong, could
    make this test pass. This version uses a dedicated `gh` stub
    (`_GH_NOTES_STUB`) that answers a `.../generate-notes` call with a canned
    body on stdout, and sets `RUNNER_TEMP` to a real writable temp dir, so
    the test is still RED right now for the genuine reason above (no
    `gh api .../generate-notes` call exists yet), and is capable of going
    GREEN once the step is implemented.
    """
    _require_tool(JQ, "jq")
    cwd = tmp_path / "work"
    cwd.mkdir()
    _write_plugin_json(cwd, name=PLUGIN_NAME)

    gh_log = tmp_path / "gh.log"
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    tag = f"{PLUGIN_NAME}--v9.9.9"
    main_sha = "cafef00d"
    orphan_sha = "deadbeef"
    canned_notes_body = "Auto-generated notes body for the driving test.\n"

    result = run_step(
        "Create tag and GitHub Release",
        env={
            "GH_TOKEN": "x",
            "VERSION": "9.9.9",
            "REPO": "acme/repo",
            "TAG": tag,
            "MAIN_SHA": main_sha,
            "PREV_TAG": prev_tag_env,
            "ORPHAN_SHA": orphan_sha,
            "ASSET": str(tmp_path / "fake-asset.zip"),
            "PRERELEASE": "false",
            "RUNNER_TEMP": str(runner_temp),
            "GH_STUB_LOG": str(gh_log),
            "GH_STUB_NOTES_BODY": canned_notes_body,
        },
        cwd=cwd,
        stub_functions={"gh": _GH_NOTES_STUB},
    )
    assert result.returncode == 0, f"stub run failed unexpectedly: {result.stderr}"

    invocations = parse_gh_log(gh_log)
    generate_notes_calls = [
        inv for inv in invocations if len(inv) >= 2 and inv[0] == "api" and "generate-notes" in inv[1]
    ]
    generate_notes_flag_used = any("--generate-notes" in inv for inv in invocations)
    notes_start_tag_flag_used = any("--notes-start-tag" in inv for inv in invocations)

    assert generate_notes_calls, (
        "expected a `gh api .../releases/generate-notes` call to compute the "
        f"release body from main's history; recorded invocations: {invocations!r}"
    )
    assert not generate_notes_flag_used, (
        "release creation must never pass --generate-notes against the "
        f"orphan commit (it has no history); recorded invocations: {invocations!r}"
    )
    assert not notes_start_tag_flag_used, (
        f"release creation must never pass --notes-start-tag; recorded invocations: {invocations!r}"
    )

    generate_notes_call = generate_notes_calls[0]
    f_values = _f_flag_values(generate_notes_call)
    assert f"tag_name=src/{tag}" in f_values, (
        f"expected -f tag_name=src/{tag}; recorded -f values: {f_values!r}"
    )
    assert f"target_commitish={main_sha}" in f_values, (
        f"expected -f target_commitish={main_sha}; recorded -f values: {f_values!r}"
    )
    if expect_previous_tag_name:
        assert f"previous_tag_name=src/{prev_tag_env}" in f_values, (
            f"expected -f previous_tag_name=src/{prev_tag_env}; recorded -f values: {f_values!r}"
        )
    else:
        assert not any(v.startswith("previous_tag_name=") for v in f_values), (
            f"expected previous_tag_name to be omitted entirely when PREV_TAG "
            f"is empty (the first-release case), not sent empty; recorded -f "
            f"values: {f_values!r}"
        )

    release_create_calls = [
        inv for inv in invocations if len(inv) >= 2 and inv[0] == "release" and inv[1] == "create"
    ]
    assert release_create_calls, f"expected a `gh release create` call; recorded invocations: {invocations!r}"
    create_call = release_create_calls[0]
    assert "--notes-file" in create_call, (
        f"expected `gh release create` to use --notes-file with the "
        f"generated-notes output; recorded invocation: {create_call!r}"
    )
    notes_file_value = _flag_value(create_call, "--notes-file")
    assert notes_file_value is not None, (
        f"expected --notes-file to carry a path argument, not a bare flag; "
        f"recorded invocation: {create_call!r}"
    )
    notes_path = pathlib.Path(notes_file_value)
    assert notes_path.is_file(), (
        f"--notes-file must point at the actual file the generate-notes "
        f"output was written to; {notes_path} does not exist -- recorded "
        f"invocation: {create_call!r}"
    )
    assert notes_path.read_text(encoding="utf-8") == canned_notes_body, (
        f"expected the --notes-file contents to match the generate-notes "
        f"stub's body {canned_notes_body!r}; got "
        f"{notes_path.read_text(encoding='utf-8')!r}"
    )
    assert "--target" in create_call and orphan_sha in create_call, (
        f"expected `gh release create` to target {orphan_sha}; recorded invocation: {create_call!r}"
    )
    assert not any("--prerelease" in inv for inv in release_create_calls), (
        f"--prerelease must not be passed when PRERELEASE=false; recorded "
        f"invocations: {release_create_calls!r}"
    )


def test_notes_generation_adds_prerelease_flag_when_version_has_suffix(tmp_path):
    """Additional coverage for R1: a prerelease version must still add
    --prerelease to the eventual `gh release create` call (unaffected by the
    notes-generation fix). This currently passes already -- the flag
    plumbing (PRERELEASE env -> --prerelease) was added by this phase's
    env: refactor of the *existing* step, which is non-behavioural
    scaffolding, not new R1 behaviour.

    Fixed from round 4 (test-critic CRITICAL): this test previously used the
    generic `gh` stub (`_GH_STUB_BODY`, which answers *every* unmatched
    `gh api <path>` call with exit 1, since GH_STUB_EXISTING_REFS is empty
    here) and never set RUNNER_TEMP. Under `bash -e`, a plan-faithful
    implementation of this step (`gh api .../generate-notes ... --jq .body >
    "$RUNNER_TEMP/notes.md"`) would abort on that line before `gh release
    create` ever ran -- so only the unfixed status-quo implementation (the
    defect this ticket removes) could ever pass this test, regardless of
    whether --prerelease plumbing was correct. This version reuses the same
    `_GH_NOTES_STUB`/RUNNER_TEMP setup as test_notes_generated_from_main_markers
    (round 3's fix for the identical problem on the sibling test) so the step
    can actually run to completion under either the old or the new
    implementation, and the --prerelease assertion is checked against real
    behavior rather than an early abort. Still additional coverage, not a
    driving RED: it passes both before and after R1 is implemented, which is
    expected for a requirement (--prerelease plumbing) this ticket does not
    change.
    """
    _require_tool(JQ, "jq")
    cwd = tmp_path / "work"
    cwd.mkdir()
    _write_plugin_json(cwd, name=PLUGIN_NAME)

    gh_log = tmp_path / "gh.log"
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    tag = f"{PLUGIN_NAME}--v9.9.9-rc.1"

    result = run_step(
        "Create tag and GitHub Release",
        env={
            "GH_TOKEN": "x",
            "VERSION": "9.9.9-rc.1",
            "REPO": "acme/repo",
            "TAG": tag,
            "MAIN_SHA": "cafef00d",
            "PREV_TAG": "",
            "ORPHAN_SHA": "deadbeef",
            "ASSET": str(tmp_path / "fake-asset.zip"),
            "PRERELEASE": "true",
            "RUNNER_TEMP": str(runner_temp),
            "GH_STUB_LOG": str(gh_log),
            "GH_STUB_NOTES_BODY": "Auto-generated notes body for the prerelease test.\n",
        },
        cwd=cwd,
        stub_functions={"gh": _GH_NOTES_STUB},
    )
    assert result.returncode == 0, f"stub run failed unexpectedly: {result.stderr}"
    invocations = parse_gh_log(gh_log)
    release_create_calls = [inv for inv in invocations if inv[:2] == ["release", "create"]]
    assert release_create_calls, f"expected a `gh release create` call; got {invocations!r}"
    assert any("--prerelease" in inv for inv in release_create_calls)


# ---------------------------------------------------------------------------
# R2 - pre-flight fails before any side effect on a violated precondition,
# and permits the first release.
# ---------------------------------------------------------------------------


# Preflight resolver invocation convention (round 4, test-critic MINOR #5):
# the plan pins tools/prev_release_tag.py to "the existing
# `python3 tools/<x>.py` shape" -- the same relative-path, cwd-at-repo-root
# invocation release.yml already uses for tools/check_plugin_payload.py
# (`python3 tools/check_plugin_payload.py --stage ...`, release.yml line 92),
# not `python3 -m tools.prev_release_tag`. These tests pin exactly that
# convention: `_preflight_repo` copies this project's own `tools/` package
# into the throwaway fixture git repo (whose cwd is NOT this project's real
# checkout) so a relative `python3 tools/prev_release_tag.py` call, run with
# cwd=<fixture repo>, resolves the module exactly as it will in CI once the
# implement phase adds tools/prev_release_tag.py. Right now (tests phase)
# that file does not exist yet, so the copy carries only the existing
# tools/__init__.py and tools/check_plugin_payload.py -- harmless, since the
# preflight step does not invoke either of those.
def _preflight_repo(tmp_path: pathlib.Path, *, plugin_name: str = PLUGIN_NAME) -> pathlib.Path:
    repo = tmp_path / "preflight-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    _write_plugin_json(repo, name=plugin_name)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    tools_src = REPO_ROOT / "tools"
    if tools_src.is_dir():
        shutil.copytree(
            tools_src, repo / "tools", ignore=shutil.ignore_patterns("__pycache__")
        )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _run_preflight(
    repo: pathlib.Path,
    *,
    version: str,
    gh_log: pathlib.Path,
    existing_refs: str,
    github_output: pathlib.Path,
    extra_env: dict | None = None,
    git_log: pathlib.Path | None = None,
) -> subprocess.CompletedProcess:
    # PYTHON_BIN is set here (posix-style, matching the plan's
    # `PurePath(sys.executable).as_posix()`) so the preflight step's
    # PREV_TAG resolution -- which the plan threads through
    # `PYTHON_BIN="${PYTHON_BIN:-python3}"` -- runs under the actual test
    # interpreter instead of silently depending on a bare `python3` on PATH.
    # This matters directly for the Windows CI leg the plan requires.
    env = {
        "GH_TOKEN": "x",
        "VERSION": version,
        "REPO": "acme/repo",
        "GH_STUB_LOG": str(gh_log),
        "GH_STUB_EXISTING_REFS": existing_refs,
        "GITHUB_OUTPUT": str(github_output),
        "PYTHON_BIN": pathlib.PurePath(sys.executable).as_posix(),
    }
    env.update(extra_env or {})
    stub_functions = {"gh": _GH_STUB_BODY}
    if git_log is not None:
        # Logs git invocations while delegating to the real git binary, so
        # the step's own git reads (shallow-check, tag listing for PREV_TAG
        # resolution) keep working against the fixture repo.
        env["GIT_STUB_LOG"] = str(git_log)
        stub_functions["git"] = _GIT_PASSTHROUGH_LOG_STUB
    return run_step(
        "Fail if tag already exists",
        env=env,
        cwd=repo,
        stub_functions=stub_functions,
    )


def test_preflight_fails_when_src_marker_already_exists(tmp_path):
    """
    Driving test for R2 case 1: an existing src/<TAG> marker (a leftover from
    a burned version) must abort with ::error:: and exit 1 -- never delete or
    move it.

    Expected RED: only the plain $TAG existence check exists today, so this
    case is not checked at all and the step exits 0.
    """
    repo = _preflight_repo(tmp_path)
    tag = f"{PLUGIN_NAME}--v9.9.9"
    gh_log = tmp_path / "gh.log"
    git_log = tmp_path / "git.log"
    result = _run_preflight(
        repo,
        version="9.9.9",
        gh_log=gh_log,
        existing_refs=f"repos/acme/repo/git/refs/tags/src/{tag}",
        github_output=tmp_path / "out1",
        git_log=git_log,
    )
    assert result.returncode == 1, (
        f"expected exit 1 when src/{tag} already exists; got {result.returncode}, "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "::error::" in result.stdout
    assert "src/" in result.stdout

    invocations = parse_gh_log(gh_log)
    delete_calls = [
        inv for inv in invocations if any(f"src/{tag}" in arg for arg in inv) and "DELETE" in inv
    ]
    assert not delete_calls, (
        f"the src/{tag} marker must never be deleted or moved via the gh "
        f"API; recorded gh invocations: {invocations!r}"
    )

    # Also cover a git-based deletion path (`git tag -d src/<tag>` or
    # `git push origin :refs/tags/src/<tag>`), which the gh-log check above
    # cannot see at all.
    git_invocations = parse_gh_log(git_log) if git_log.exists() else []
    git_delete_calls = [
        inv
        for inv in git_invocations
        if any(f"src/{tag}" in arg for arg in inv)
        and (
            "-d" in inv
            or any(arg.startswith(":") and f"src/{tag}" in arg for arg in inv)
        )
    ]
    assert not git_delete_calls, (
        f"the src/{tag} marker must never be deleted via git either (`git "
        f"tag -d` or `git push origin :refs/tags/...`); recorded git "
        f"invocations: {git_invocations!r}"
    )


def test_preflight_fails_when_prev_tag_marker_missing(tmp_path):
    """
    Driving test for R2 case 2: a resolvable PREV_TAG whose src/<PREV_TAG>
    marker is missing must abort with both exact bootstrap commands quoted
    in the error, exit 1.

    Expected RED: PREV_TAG resolution and the marker check do not exist yet.
    """
    repo = _preflight_repo(tmp_path)
    prev_tag = f"{PLUGIN_NAME}--v1.0.0"
    subprocess.run(["git", "tag", prev_tag], cwd=repo, check=True)
    result = _run_preflight(
        repo,
        version="1.1.0",
        gh_log=tmp_path / "gh.log",
        existing_refs="",  # neither TAG nor src/PREV_TAG exists remotely
        github_output=tmp_path / "out2",
    )
    assert result.returncode == 1, (
        f"expected exit 1 when src/{prev_tag} marker is missing; got "
        f"{result.returncode}, stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "::error::" in result.stdout
    assert f"src/{prev_tag}" in result.stdout
    assert re.search(rf"git\s+tag\s+\S*src/{re.escape(prev_tag)}\S*", result.stdout), (
        f"the error must quote the exact tag-bootstrap command referencing "
        f"src/{prev_tag}, not just the bare word 'git tag'; stdout={result.stdout!r}"
    )
    assert re.search(rf"git\s+push\s+origin\s+\S*src/{re.escape(prev_tag)}\S*", result.stdout), (
        f"the error must quote the exact push-bootstrap command referencing "
        f"origin and src/{prev_tag}, not just the bare words 'git push'; "
        f"stdout={result.stdout!r}"
    )


def test_preflight_permits_first_release_with_notice_and_empty_prev_tag(tmp_path):
    """
    Driving test for R2 case 3: with no prior `<plugin>--v*` tag at all, the
    step must exit 0, print an ::notice:: about the first release, and export
    an empty `prev_tag` output.

    Expected RED: exit 0 is already achieved trivially (no conflicting tag),
    but no ::notice:: is printed and no $GITHUB_OUTPUT entries exist at all.
    """
    repo = _preflight_repo(tmp_path)
    github_output = tmp_path / "out3"
    result = _run_preflight(
        repo,
        version="0.1.0",
        gh_log=tmp_path / "gh.log",
        existing_refs="",
        github_output=github_output,
    )
    assert result.returncode == 0, (
        f"expected exit 0 on a genuinely first release; got {result.returncode}, "
        f"stderr={result.stderr!r}"
    )
    assert "::notice::" in result.stdout, (
        "first release must print an ::notice:: distinguishing it from a "
        "history-not-fetched false negative"
    )
    outputs = github_output.read_text(encoding="utf-8") if github_output.exists() else ""
    assert re.search(r"^prev_tag=$", outputs, re.MULTILINE), (
        f"expected an empty prev_tag= output line; $GITHUB_OUTPUT contents: {outputs!r}"
    )


def test_preflight_notice_not_printed_when_prev_tag_resolves(tmp_path):
    """
    Additional coverage for R2 case 3 (negative): when a previous release
    DOES resolve, the first-release ::notice:: must NOT be printed -- proving
    the notice is conditional on a genuinely absent prior tag, not
    unconditional. Uses the same happy-path-style fixture (a real previous
    tag with its src/* marker present) as the case-6 happy-path test.

    Note: this currently passes trivially, since the step never prints
    ::notice:: at all yet -- it is reported as additional coverage, not a
    driving RED, per the plan (only case 3's positive assertion above is the
    designed RED for the notice requirement).
    """
    repo = _preflight_repo(tmp_path)
    prev_tag = f"{PLUGIN_NAME}--v1.0.0"
    subprocess.run(["git", "tag", prev_tag], cwd=repo, check=True)
    result = _run_preflight(
        repo,
        version="1.1.0",
        gh_log=tmp_path / "gh.log",
        existing_refs=f"repos/acme/repo/git/refs/tags/src/{prev_tag}",
        github_output=tmp_path / "out3b",
        extra_env={"REF_NAME": "main", "DEFAULT_BRANCH": "main"},
    )
    assert result.returncode == 0, (
        f"expected exit 0 on the happy path; got {result.returncode}, "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "::notice::" not in result.stdout, (
        "the first-release ::notice:: must not fire when a previous release "
        f"tag resolves; stdout={result.stdout!r}"
    )


def test_preflight_fails_on_shallow_repository(tmp_path):
    """
    Driving test for R2 case 4: a shallow checkout (fetch-depth not 0) must
    abort with exit 1 before any tag/notes work, since history cannot be
    walked reliably.

    Expected RED: shallow-repo detection does not exist yet, so the step
    exits 0 regardless of --is-shallow-repository.
    """
    _require_tool(shutil.which("git"), "git")
    origin = _preflight_repo(tmp_path)
    # A second commit so the depth-1 clone is genuinely shallow (a 1-commit
    # repo can't be meaningfully "shallow").
    (origin / "second.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=origin, check=True)

    shallow = tmp_path / "shallow-clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", origin.as_uri(), str(shallow)], check=True
    )
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=shallow, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=shallow, check=True)

    result = _run_preflight(
        shallow,
        version="0.1.0",
        gh_log=tmp_path / "gh.log",
        existing_refs="",
        github_output=tmp_path / "out4",
    )
    assert result.returncode == 1, (
        f"expected exit 1 on a shallow repository; got {result.returncode}, "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_preflight_fails_when_ref_name_is_not_default_branch(tmp_path):
    """
    Driving test for R2 case 5: dispatching from any ref other than the
    repository's default branch must abort with exit 1.

    Expected RED: no ref-name/default-branch check exists yet, so the step
    exits 0 regardless of REF_NAME vs DEFAULT_BRANCH.
    """
    repo = _preflight_repo(tmp_path)
    result = _run_preflight(
        repo,
        version="0.1.0",
        gh_log=tmp_path / "gh.log",
        existing_refs="",
        github_output=tmp_path / "out5",
        extra_env={"REF_NAME": "some-feature-branch", "DEFAULT_BRANCH": "main"},
    )
    assert result.returncode == 1, (
        f"expected exit 1 when REF_NAME != DEFAULT_BRANCH; got "
        f"{result.returncode}, stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_preflight_happy_path_exports_all_four_outputs(tmp_path):
    """
    Driving test for R2 case 6: with every precondition satisfied (tag not
    taken, src/<PREV_TAG> present, non-shallow repo, dispatched from the
    default branch), the step must exit 0 and export tag, plugin_name,
    prev_tag, main_sha as step outputs.

    Expected RED: exit 0 is already achieved, but zero outputs are exported
    ("case 6 exports nothing", per the plan). Tightened from a prior round:
    a bare `{key}=` prefix match would pass for any value (including a
    wrong one); this now requires the actual expected values.

    Fixed from round 4 (test-critic MINOR #4): a single fixture cannot tell
    a correct implementation apart from one that hardcodes the expected
    tag/plugin_name as constants -- both satisfy one fixed VERSION/
    plugin.json pair equally well. This now runs the same assertions against
    two independent fixtures with a different VERSION and a different
    `.claude-plugin/plugin.json` plugin name each, and additionally asserts
    the two runs' tag/plugin_name outputs actually differ from each other.
    """
    outputs_by_case: dict[str, dict[str, str]] = {}
    for case_name, plugin_name, version in (
        ("case-a", PLUGIN_NAME, "1.1.0"),
        ("case-b", "another-test-plugin", "2.5.0"),
    ):
        case_root = tmp_path / case_name
        case_root.mkdir()
        repo = _preflight_repo(case_root, plugin_name=plugin_name)
        prev_tag = f"{plugin_name}--v1.0.0"
        subprocess.run(["git", "tag", prev_tag], cwd=repo, check=True)
        expected_main_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        github_output = case_root / "github_output"
        result = _run_preflight(
            repo,
            version=version,
            gh_log=case_root / "gh.log",
            # src/<prev_tag> marker exists remotely -> precondition satisfied.
            existing_refs=f"repos/acme/repo/git/refs/tags/src/{prev_tag}",
            github_output=github_output,
            extra_env={"REF_NAME": "main", "DEFAULT_BRANCH": "main"},
        )
        assert result.returncode == 0, (
            f"[{case_name}] expected exit 0 on the happy path; got "
            f"{result.returncode}, stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        outputs = _parse_github_output(
            github_output.read_text(encoding="utf-8") if github_output.exists() else ""
        )
        expected_tag = f"{plugin_name}--v{version}"
        assert outputs.get("tag") == expected_tag, (
            f"[{case_name}] expected tag={expected_tag}; $GITHUB_OUTPUT contents: {outputs!r}"
        )
        assert outputs.get("plugin_name") == plugin_name, (
            f"[{case_name}] expected plugin_name={plugin_name}; $GITHUB_OUTPUT contents: {outputs!r}"
        )
        assert outputs.get("prev_tag") == prev_tag, (
            f"[{case_name}] expected prev_tag={prev_tag}; $GITHUB_OUTPUT contents: {outputs!r}"
        )
        assert outputs.get("main_sha") == expected_main_sha, (
            f"[{case_name}] expected main_sha={expected_main_sha}; $GITHUB_OUTPUT contents: {outputs!r}"
        )
        outputs_by_case[case_name] = outputs

    assert outputs_by_case["case-a"]["tag"] != outputs_by_case["case-b"]["tag"], (
        "both fixtures' tag outputs matched -- a hardcoded-constant "
        f"implementation could survive this test: {outputs_by_case!r}"
    )
    assert outputs_by_case["case-a"]["plugin_name"] != outputs_by_case["case-b"]["plugin_name"], (
        "both fixtures' plugin_name outputs matched -- a hardcoded-constant "
        f"implementation could survive this test: {outputs_by_case!r}"
    )


def test_preflight_prev_tag_resolution_ignores_src_marker_and_lexical_order(tmp_path):
    """
    Additional coverage for R2 case 6 (resolver-integration): a leftover
    src/<TAG> marker tag from a burned version, plus a real previous tag that
    sorts *before* an older one lexically (though after it in semver order),
    must not derail PREV_TAG resolution -- proving the preflight step
    delegates to the real semver/scope-aware resolver (R3) rather than a
    naive `git tag | tail -1`.

    Expected RED: no PREV_TAG resolution exists yet, so no prev_tag= output
    is exported at all.
    """
    repo = _preflight_repo(tmp_path)
    semver_highest_real_tag = f"{PLUGIN_NAME}--v0.10.0"
    lexically_last_but_semver_older = f"{PLUGIN_NAME}--v0.9.0"
    burned_marker = f"src/{PLUGIN_NAME}--v0.11.0"  # lexically last of all (starts with 's')
    for t in (lexically_last_but_semver_older, semver_highest_real_tag, burned_marker):
        subprocess.run(["git", "tag", t], cwd=repo, check=True)

    github_output = tmp_path / "out8"
    result = _run_preflight(
        repo,
        version="1.0.0",
        gh_log=tmp_path / "gh.log",
        existing_refs=f"repos/acme/repo/git/refs/tags/src/{semver_highest_real_tag}",
        github_output=github_output,
        extra_env={"REF_NAME": "main", "DEFAULT_BRANCH": "main"},
    )
    assert result.returncode == 0, (
        f"expected exit 0 on the happy path; got {result.returncode}, "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    outputs = _parse_github_output(github_output.read_text(encoding="utf-8") if github_output.exists() else "")
    assert outputs.get("prev_tag") == semver_highest_real_tag, (
        f"expected prev_tag={semver_highest_real_tag} (the semver-highest "
        f"real tag, ignoring the src/* marker and lexical ordering); "
        f"$GITHUB_OUTPUT contents: {outputs!r}"
    )


def test_preflight_tag_already_exists_still_fails_first(tmp_path):
    """Additional coverage: the pre-existing $TAG-already-exists check (not
    part of this ticket) must keep working even once other preconditions are
    added -- an existing $TAG must dominate over any other case. This is the
    one case that may already pass, since the check predates this ticket."""
    repo = _preflight_repo(tmp_path)
    tag = f"{PLUGIN_NAME}--v2.0.0"
    result = _run_preflight(
        repo,
        version="2.0.0",
        gh_log=tmp_path / "gh.log",
        existing_refs=f"repos/acme/repo/git/refs/tags/{tag}",
        github_output=tmp_path / "out7",
    )
    assert result.returncode == 1
    assert "already exists" in result.stdout


# ---------------------------------------------------------------------------
# R3 - tools/prev_release_tag.py: strict-semver resolution + scope
# exclusions; the workflow regex matches the same grammar.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidates,expected",
    [
        (
            [f"{PLUGIN_NAME}--v1.0.0-rc.2", f"{PLUGIN_NAME}--v1.0.0-rc.10"],
            f"{PLUGIN_NAME}--v1.0.0-rc.10",
        ),
        (
            [f"{PLUGIN_NAME}--v1.0.0-rc.1", f"{PLUGIN_NAME}--v1.0.0"],
            f"{PLUGIN_NAME}--v1.0.0",
        ),
        (
            [f"{PLUGIN_NAME}--v0.9.0", f"{PLUGIN_NAME}--v0.10.0"],
            f"{PLUGIN_NAME}--v0.10.0",
        ),
    ],
    ids=["rc2-lt-rc10", "prerelease-lt-release", "minor-0.9-lt-0.10"],
)
def test_prev_release_tag_orders_by_strict_semver(candidates, expected):
    """
    Driving test for R3: previous_release_tag() must order candidates by
    strict-semver precedence, not lexicographically (which would wrongly put
    "rc.10" before "rc.2", or "0.9.0" after "0.10.0").

    Expected RED: ModuleNotFoundError: No module named 'tools.prev_release_tag'
    (the module does not exist yet -- this is the plan's own designed RED
    for R3, not an accidental import failure).
    """
    import tools.prev_release_tag as prt

    result = prt.previous_release_tag(
        candidates, plugin_name=PLUGIN_NAME, exclude_tag=f"{PLUGIN_NAME}--v99.0.0"
    )
    assert result == expected


def test_prev_release_tag_excludes_current_tag_foreign_plugin_and_src_and_malformed():
    """
    Driving test for R3: resolution must exclude the tag being created, tags
    belonging to a different plugin, any src/* marker tag, and malformed
    tags -- returning the highest remaining <plugin>--v* tag.

    Expected RED: ModuleNotFoundError (module absent).
    """
    import tools.prev_release_tag as prt

    candidates = [
        f"{PLUGIN_NAME}--v1.0.0",
        f"{PLUGIN_NAME}--v2.0.0",  # excluded: the tag being created
        "some-other-plugin--v9.9.9",  # excluded: foreign plugin
        f"src/{PLUGIN_NAME}--v1.5.0",  # excluded: marker namespace
        f"{PLUGIN_NAME}--v-not-semver",  # excluded: malformed
    ]
    result = prt.previous_release_tag(
        candidates, plugin_name=PLUGIN_NAME, exclude_tag=f"{PLUGIN_NAME}--v2.0.0"
    )
    assert result == f"{PLUGIN_NAME}--v1.0.0"


def test_prev_release_tag_empty_input_returns_none():
    """Driving test for R3 (empty case): no candidates -> None, no crash.

    Expected RED: ModuleNotFoundError (module absent)."""
    import tools.prev_release_tag as prt

    result = prt.previous_release_tag(
        [], plugin_name=PLUGIN_NAME, exclude_tag=f"{PLUGIN_NAME}--v1.0.0"
    )
    assert result is None


def test_prev_release_tag_cli_empty_stdin_exits_zero_and_prints_nothing(monkeypatch, capsys):
    """Additional coverage for R3: the CLI reads candidate tags on stdin and
    exits 0 with empty stdout when nothing resolves.

    Expected RED: ModuleNotFoundError (module absent)."""
    import tools.prev_release_tag as prt

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    exit_code = prt.main(["--plugin-name", PLUGIN_NAME, "--exclude-tag", f"{PLUGIN_NAME}--v1.0.0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_prev_release_tag_cli_multi_tag_stdin_prints_resolved_tag(monkeypatch, capsys):
    """
    Additional coverage for R3: feeding the CLI a real multi-tag stdin (reusing
    the table-driven fixture from test_prev_release_tag_orders_by_strict_semver)
    must print the correctly-resolved tag to stdout. A stub `def main(argv):
    return 0` would satisfy the empty-stdin case above but not this one.

    Expected RED: ModuleNotFoundError (module absent).
    """
    import tools.prev_release_tag as prt

    candidates = [
        f"{PLUGIN_NAME}--v1.0.0-rc.2",
        f"{PLUGIN_NAME}--v1.0.0-rc.10",
        f"{PLUGIN_NAME}--v0.9.0",
    ]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(candidates) + "\n"))
    exit_code = prt.main(["--plugin-name", PLUGIN_NAME, "--exclude-tag", f"{PLUGIN_NAME}--v99.0.0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == f"{PLUGIN_NAME}--v1.0.0-rc.10", (
        f"expected the highest strict-semver candidate on stdout; got {captured.out!r}"
    )


def _extract_workflow_version_regex() -> str:
    text = _workflow_text()
    match = re.search(r'\[\[ ! "\$V" =~ (\^.*\$) \]\]', text)
    assert match, "could not find the validate-step semver regex in release.yml"
    return match.group(1)


@pytest.mark.parametrize(
    "candidate,accepted",
    [
        ("1.2.3", True),
        ("1.2.3-rc.10", True),
        ("01.2.3", False),  # leading zero: illegal in strict semver
        ("1.2", False),  # missing patch component
        ("1.2.3+build", False),  # build metadata: illegal in a git tag / marketplace ref
        ("1.2.3-", False),  # empty prerelease identifier
    ],
)
def test_workflow_version_regex_matches_module_parser_grammar(candidate, accepted):
    """
    Driving test for R3's grammar-consistency requirement (plan-critic note
    2): since this repo has no ported `prev-release-tag.sh` to compare
    against, the plan's own new module is the grammar authority. The
    workflow's validate-step regex (POSIX ERE, also valid Python `re` per the
    plan) must accept/reject exactly the same strings as the module's
    VERSION_RE.

    Expected RED: ModuleNotFoundError (module absent) for every row -- once
    the module exists, this also pins that release.yml's regex was tightened
    to strict semver (no leading zeros, no build metadata) to match it.
    """
    import tools.prev_release_tag as prt

    workflow_regex = re.compile(_extract_workflow_version_regex())
    assert bool(workflow_regex.match(candidate)) == accepted, (
        f"workflow validate-step regex disagrees with the expected grammar "
        f"for {candidate!r} (expected accepted={accepted})"
    )
    assert bool(prt.VERSION_RE.match(candidate)) == accepted, (
        f"tools.prev_release_tag.VERSION_RE disagrees with the expected "
        f"grammar for {candidate!r} (expected accepted={accepted})"
    )


# ---------------------------------------------------------------------------
# R4 - src/<TAG> is pushed unconditionally at MAIN_SHA, after build success
# and before the orphan push.
# ---------------------------------------------------------------------------


def test_source_tag_push_is_unconditional(tmp_path):
    """
    Driving test for R4: the "Push source tag" step must push
    refs/tags/src/<TAG> at MAIN_SHA even when a stub `gh` reports that ref (or
    any other existence-check target) already exists -- proving there is no
    skip-if-exists guard.

    Expected RED (round 2 fix): the prior round asserted the step's ABSENCE
    (`pytest.raises(AssertionError, match="Push source tag")`), which can
    never go green once the step exists correctly -- a wrong implementation
    would make it fail forever. This version invokes the step directly and
    asserts on the recorded `git` argv; right now the step genuinely does not
    exist, so `run_step`'s own step-lookup assertion
    (`release.yml has no step named 'Push source tag'`) fires and fails the
    test before any push logic runs -- a real gap, not a broken assertion.
    """
    cwd = tmp_path / "work"
    cwd.mkdir()
    git_log = tmp_path / "git.log"
    gh_log = tmp_path / "gh.log"
    tag = f"{PLUGIN_NAME}--v1.0.0"
    main_sha = "cafef00d"

    result = run_step(
        "Push source tag",
        env={
            "REPO": "acme/repo",
            "GH_TOKEN": "x",
            "TAG": tag,
            "MAIN_SHA": main_sha,
            "DEFAULT_BRANCH": "main",
            "GIT_STUB_LOG": str(git_log),
            "GH_STUB_LOG": str(gh_log),
            # remote default-branch tip matches MAIN_SHA -> no abort expected.
            "GH_STUB_TIP_JSON": json.dumps({"object": {"sha": main_sha}}),
        },
        cwd=cwd,
        stub_functions={"git": _GIT_LOG_STUB, "gh": _GH_PUSH_STEP_STUB},
    )
    assert result.returncode == 0, f"push step failed unexpectedly: {result.stderr}"
    git_invocations = parse_gh_log(git_log)
    push_calls = [
        inv
        for inv in git_invocations
        if len(inv) >= 1 and inv[0] == "push" and any(f"refs/tags/src/{tag}" in arg for arg in inv)
    ]
    assert push_calls, (
        f"expected `git push origin refs/tags/src/{tag}` to be recorded "
        f"unconditionally (even though the stub gh reports the ref already "
        f"exists); recorded git invocations: {git_invocations!r}"
    )

    # The "pushed unconditionally AT MAIN_SHA" requirement is only proven by
    # checking the `git tag` invocation itself carries both the marker name
    # and MAIN_SHA as its arguments -- a push alone doesn't show what commit
    # the tag object was created at.
    tag_calls = [
        inv
        for inv in git_invocations
        if len(inv) >= 1 and inv[0] == "tag" and f"src/{tag}" in inv and main_sha in inv
    ]
    assert tag_calls, (
        f"expected `git tag src/{tag} {main_sha}` to be recorded (the tag "
        f"created at MAIN_SHA, not just pushed); recorded git invocations: "
        f"{git_invocations!r}"
    )


def test_source_tag_push_aborts_on_tip_mismatch(tmp_path):
    """
    Driving test for R4: when the remote default-branch tip differs from
    MAIN_SHA (a dispatch-to-push race), the step must abort without pushing
    and exit non-zero.

    Expected RED (round 2 fix): same reasoning as
    test_source_tag_push_is_unconditional above -- this asserts real
    behaviour instead of the step's absence. Right now the step genuinely
    does not exist, so run_step's own step-lookup AssertionError fires and
    fails the test before any push logic runs.

    Fixed from round 4 (test-critic MAJOR): a plan-faithful implementation of
    the tip-mismatch comparison plausibly shells out to `jq` (e.g. to pick
    `.object.sha` back out of the JSON `run_step` command's own recorded
    output, or to compare payloads) the same way the R5/R6 dispatch tests'
    `_run_dispatch` already requires `jq` via `_require_tool(JQ, "jq")`. On a
    machine without `jq`, a correct implementation would die from that
    unrelated tooling gap, not from the tip-mismatch logic under test -- which
    would make this test pass here (exit 1) for the wrong reason instead of
    skipping outright. Require `jq` explicitly so the test is skipped (or
    raises under ADEV_REQUIRE_SHELL_TOOLING=1) on such a machine instead of
    silently passing on a false premise.
    """
    _require_tool(JQ, "jq")
    cwd = tmp_path / "work"
    cwd.mkdir()
    git_log = tmp_path / "git.log"
    gh_log = tmp_path / "gh.log"
    tag = f"{PLUGIN_NAME}--v1.0.0"
    main_sha = "cafef00d"
    differing_tip = "0000000000000000000000000000000000000000"

    result = run_step(
        "Push source tag",
        env={
            "REPO": "acme/repo",
            "GH_TOKEN": "x",
            "TAG": tag,
            "MAIN_SHA": main_sha,
            "DEFAULT_BRANCH": "main",
            "GIT_STUB_LOG": str(git_log),
            "GH_STUB_LOG": str(gh_log),
            "GH_STUB_TIP_JSON": json.dumps({"object": {"sha": differing_tip}}),
        },
        cwd=cwd,
        stub_functions={"git": _GIT_LOG_STUB, "gh": _GH_PUSH_STEP_STUB},
    )
    assert result.returncode == 1, (
        f"expected exit 1 on a remote default-branch tip mismatch; got "
        f"{result.returncode}, stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    git_invocations = parse_gh_log(git_log) if git_log.exists() else []
    push_calls = [inv for inv in git_invocations if len(inv) >= 1 and inv[0] == "push"]
    assert not push_calls, (
        f"expected no push when the remote default-branch tip differs from "
        f"MAIN_SHA; recorded git invocations: {git_invocations!r}"
    )


def test_source_tag_push_step_ordering_is_between_payload_check_and_orphan_push():
    """
    Driving test for R4 (structural): "Push source tag" must sit strictly
    after "Verify referenced plugin files are staged" and strictly before
    "Push orphan release branch and capture commit", asserted from the
    parsed YAML step list, not a text search.

    Expected RED: the step does not exist, so its index lookup returns None
    and the ordering assertion fails with a clear message.
    """
    steps = _release_steps()
    payload_check_idx = _step_index("Verify referenced plugin files are staged", steps)
    push_source_tag_idx = _step_index("Push source tag", steps)
    orphan_push_idx = _step_index("Push orphan release branch and capture commit", steps)

    assert payload_check_idx is not None
    assert orphan_push_idx is not None
    assert push_source_tag_idx is not None, (
        "release.yml has no 'Push source tag' step yet -- expected, R4 is not "
        "implemented in this phase."
    )
    assert payload_check_idx < push_source_tag_idx < orphan_push_idx


# ---------------------------------------------------------------------------
# R5 - the changelog reaches the dispatch payload byte-exactly, losing
# exactly one trailing newline.
# ---------------------------------------------------------------------------


# A hostile body: backticks, single quotes, a command substitution, a shell
# variable expansion, a blank line, and two trailing newlines (one "real"
# content newline plus one blank-line newline) -- the round trip must lose
# exactly one of those two.
_HOSTILE_BODY = (
    "Release notes with `backticks`, 'quotes', $(rm -rf /), and ${HOME}.\n"
    "\n"
    "Second paragraph.\n"
    "\n"
)


def _run_dispatch(
    tmp_path: pathlib.Path,
    *,
    body_file: pathlib.Path | None,
) -> tuple[subprocess.CompletedProcess, pathlib.Path]:
    _require_tool(JQ, "jq")
    cwd = tmp_path / "work"
    cwd.mkdir()
    _write_plugin_json(cwd, name=PLUGIN_NAME, description="A test plugin")

    payload_file = tmp_path / "payload.json"
    env = {
        "GH_TOKEN": "x",
        "GH_PAT": "y",
        "VERSION": "9.9.9",
        "REPO": "acme/repo",
        # Set per the plan's env: convention (TAG threaded in, not
        # re-derived from plugin.json name + VERSION downstream) so these
        # tests check the plan-faithful TAG-from-env derivation rather than
        # accidentally pinning the old duplicated derivation the plan
        # removes.
        "TAG": f"{PLUGIN_NAME}--v9.9.9",
        "GH_STUB_LOG": str(tmp_path / "gh.log"),
        "GH_STUB_EXISTING_REFS": "",
        "CURL_STUB_PAYLOAD_FILE": str(payload_file),
    }
    if body_file is not None:
        env["GH_STUB_BODY_FILE"] = str(body_file)
    result = run_step(
        "Dispatch to agent-marketplace",
        env=env,
        cwd=cwd,
        stub_functions={"gh": _GH_STUB_BODY, "curl": _CURL_STUB_BODY},
    )
    return result, payload_file


def test_dispatch_changelog_roundtrip(tmp_path):
    """
    Driving test for R5: a hostile release body must round-trip into
    client_payload.changelog losing exactly one trailing newline.

    Expected RED: the current capture (`CHANGELOG=$(gh release view ... -q
    .body)`) strips *all* trailing newlines via command substitution and has
    no `&& printf x` guard, so a body ending in a blank line mismatches the
    expected one-newline-lost round trip.
    """
    body_file = tmp_path / "body.txt"
    body_file.write_text(_HOSTILE_BODY, encoding="utf-8", newline="\n")

    result, payload_file = _run_dispatch(tmp_path, body_file=body_file)
    assert result.returncode == 0, f"dispatch step failed: {result.stderr}"
    assert payload_file.exists(), "curl stub did not capture a payload"

    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    changelog = payload["client_payload"]["changelog"]
    expected = _HOSTILE_BODY[:-1]  # lose exactly one trailing newline
    assert changelog == expected, (
        f"expected changelog to lose exactly one trailing newline; "
        f"expected={expected!r}, got={changelog!r}"
    )


def test_dispatch_unrelated_payload_fields_unaffected(tmp_path):
    """Additional coverage for R5 (may already pass -- overlaps
    tests/test_release_payload.py): tags/ref/version survive the round trip
    unchanged regardless of the changelog fix."""
    body_file = tmp_path / "body.txt"
    body_file.write_text("simple body\n", encoding="utf-8", newline="\n")
    result, payload_file = _run_dispatch(tmp_path, body_file=body_file)
    assert result.returncode == 0, f"dispatch step failed: {result.stderr}"
    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    client_payload = payload["client_payload"]
    assert client_payload["tags"] == ["git", "organisation", "ticket", "automation"]
    assert client_payload["ref"] == f"{PLUGIN_NAME}--v9.9.9"
    assert client_payload["version"] == "9.9.9"


# ---------------------------------------------------------------------------
# R6 - the changelog key is omitted entirely when the body is empty.
# ---------------------------------------------------------------------------


def test_dispatch_omits_empty_changelog(tmp_path):
    """
    Driving test for R6: an empty release body must omit the `changelog` key
    entirely from client_payload, while every other key survives.

    Expected RED: the jq filter always sets `changelog: $changelog`
    (currently ""), so the key is present with an empty-string value instead
    of being absent.
    """
    body_file = tmp_path / "body.txt"
    body_file.write_text("", encoding="utf-8")  # empty body

    result, payload_file = _run_dispatch(tmp_path, body_file=body_file)
    assert result.returncode == 0, f"dispatch step failed: {result.stderr}"
    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    client_payload = payload["client_payload"]

    assert "changelog" not in client_payload, (
        f"expected 'changelog' to be omitted entirely for an empty body; "
        f"client_payload={client_payload!r}"
    )
    for key in ("name", "description", "repo", "version", "ref", "tags"):
        assert key in client_payload, f"expected {key!r} to survive; client_payload={client_payload!r}"
