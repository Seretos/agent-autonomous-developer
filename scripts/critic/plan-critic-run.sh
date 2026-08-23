#!/usr/bin/env bash
#
# Runs the plan critique as three isolated critics and merges their findings.
#
# ISOLATION
#
# The entire value of the plan-critic role rests on each critique running WITHOUT the project's
# context: no CLAUDE.md, no ticket beyond what the package contains, no skills, no agent
# definitions, no MCP servers, no tools, no plugins. A critic sees exactly the review package it
# is handed and nothing else. That is what makes its answer independently derived rather than a
# reworded echo of the same context the plan was written in.
#
# Every isolation flag below is load-bearing, and the flag set is deliberately identical across
# both runners (this one and test-critic-run.sh). Measured on this machine (2026-07-30, claude 2.1.220; re-measured 2026-08-14, claude
# 2.1.229): a plain `claude -p` started in an empty directory inherits user-level plugins, their
# skills, their MCP servers and their hooks — and it also reads a CLAUDE.md sitting in its own
# working directory. Until 2026-08-14 this comment claimed the opposite about that last point. The
# claim was wrong; it understated the exposure rather than weakening the gate, since the flags do
# exclude all of it. Dropping `--setting-sources ""` silently re-contaminates the critic.
# Do not "simplify" this invocation. The guarantee applies per process, so all three runs get the
# identical flag set and each writes its own provenance record — three isolated runs, not one run
# whose isolation is assumed to cover the others.
#
# The static half of check-critic-isolation.sh runs below, on every invocation of this script, so
# this comment is not the only thing standing between a CLI change and a silently contaminated run.
# The expensive --live measurement stays a deliberate act.
#
# THREE LENSES
#
# One critic reading for everything at once reads for nothing in particular: it finds whichever
# weakness is most conspicuous and stops. The three runs are identical — same package, same system
# prompt, same isolation — except for a fixed focus block, so each stumbles over a different class
# of defect: requirements the plan never addresses, requirements it addresses but misreads, and
# behaviour stated too vaguely for a failing test to be derived from it. The lens texts are fixed
# in plan-critic-package.sh; nothing here or above it chooses them.
#
# The runs are independent by construction and are therefore started in parallel: they never see
# each other's output, which is what keeps the three results three data points rather than one
# opinion agreed to three times.
#
# MERGE
#
# The findings are merged by plan-critic-merge.py — plain deterministic code, no model. See that
# file for why that matters. This script's exit code is 0 only if all three critics returned a
# usable critique; a partial run is written out but reported as a failure, because a 2-of-3 gate
# that looks complete is worse than one that says it is not.
#
# Usage: plan-critic-run.sh <spec-file> <scope-file> <plan-file> <output-dir>
#   spec-file    the ticket package (title, body, comments; for an epic: plus all children), verbatim
#
# Writes into <output-dir>, per lens <L>:
#   package-<L>.txt              the assembled review package (diff these: only PART 5 differs)
#   critique-<L>.raw.json        the CLI result envelope, untouched
#   critique-<L>.json            the validated critique object, as the schema defines it
#   critique-<L>.provenance.txt  how that process was actually started
#   critique-<L>.stderr.txt      its stderr
# and once, across all lenses:
#   critique-merged.json         the merged findings the dispatching skill reads
#
set -euo pipefail

if [ $# -ne 4 ]; then
  echo "usage: $0 <spec-file> <scope-file> <plan-file> <output-dir>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# python3 is the usual name; on a Windows host with the Store launcher it may only exist as `python`.
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "python3/python not found on PATH" >&2; exit 2; }

# --- isolation pre-flight ------------------------------------------------------------------------
# The static half of the isolation check runs here, on every gate invocation, instead of being asked
# for in prose. The prose version existed in the project this was ported from and was measurably
# not followed: the recorded live measurement sat three CLI upgrades behind the installed version,
# and nothing had noticed. An instruction that depends on somebody remembering it is not a check.
# Costs about a second and no API call; the expensive --live measurement stays a deliberate act.
# Its own output is suppressed on success, so a green pre-flight is silent and a failure is not.
if ! "$SCRIPT_DIR/check-critic-isolation.sh" >/dev/null; then
  echo "FATAL: the isolation pre-flight failed (detail above). Refusing to run a gate whose" >&2
  echo "       isolation is unproven — a contaminated critique is worse than no critique." >&2
  exit 1
fi

SPEC="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
SCOPE="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
PLAN="$(cd "$(dirname "$3")" && pwd)/$(basename "$3")"
mkdir -p "$4"
# Canonical, drive-qualified form — every path this script reports is derived from it, and
# plan-critic reads those reports with native file tools that resolve a bare "/tmp/…" somewhere
# else entirely. See win-path.sh.
. "$SCRIPT_DIR/win-path.sh"
OUTDIR="$(canonical_dir "$4")"

SCHEMA="$SCRIPT_DIR/plan-critic-schema.json"
SYSPROMPT="$SCRIPT_DIR/plan-critic-system-prompt.txt"
PACKAGER="$SCRIPT_DIR/plan-critic-package.sh"
MERGER="$SCRIPT_DIR/plan-critic-merge.py"

for f in "$SPEC" "$SCOPE" "$PLAN" "$SCHEMA" "$SYSPROMPT" "$PACKAGER" "$MERGER"; do
  [ -f "$f" ] || { echo "missing required file: $f" >&2; exit 2; }
done

# The lens list comes from the packager, so there is exactly one place that defines which lenses
# exist and this script cannot drift out of step with it.
LENSES="$(bash "$PACKAGER" --list-lenses)"

run_one_lens() {
  local lens="$1"
  local pkg="$OUTDIR/package-$lens.txt"
  local raw="$OUTDIR/critique-$lens.raw.json"
  local out="$OUTDIR/critique-$lens.json"
  local prov="$OUTDIR/critique-$lens.provenance.txt"
  local err="$OUTDIR/critique-$lens.stderr.txt"

  bash "$PACKAGER" "$SPEC" "$SCOPE" "$PLAN" "$lens" "$pkg" >/dev/null

  # A fresh, empty directory outside the repository, one per lens. Not a worktree, not a
  # subdirectory of the project — CLAUDE.md discovery walks parent directories, so anything under
  # the repo root would defeat the isolation.
  local workdir
  workdir="$(mktemp -d)"

  {
    echo "plan-critic isolated run"
    echo "lens: $lens"
    echo "timestamp_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "claude_version: $(claude --version 2>&1)"
    echo "cwd: $workdir"
    echo "cwd_contents: $(ls -A "$workdir" | tr '\n' ' ')<empty above means no inherited project files>"
    echo "package: $pkg"
    echo "package_sha256: $(sha256sum "$pkg" | cut -d' ' -f1)"
    echo "package_bytes: $(wc -c < "$pkg")"
    echo "spec_sha256: $(sha256sum "$SPEC" | cut -d' ' -f1)"
    echo "plan_sha256: $(sha256sum "$PLAN" | cut -d' ' -f1)"
    echo "system_prompt_sha256: $(sha256sum "$SYSPROMPT" | cut -d' ' -f1)"
    echo "isolation_flags: --setting-sources '' --strict-mcp-config --disable-slash-commands --tools '' --system-prompt <file> --json-schema <file>"
    echo "model: opus"
  } > "$prov"

  set +e
  (
    cd "$workdir" && claude -p \
      --model opus \
      --effort high \
      --setting-sources "" \
      --strict-mcp-config \
      --disable-slash-commands \
      --tools "" \
      --system-prompt "$(cat "$SYSPROMPT")" \
      --output-format json \
      --json-schema "$(cat "$SCHEMA")" \
      < "$pkg"
  ) > "$raw" 2> "$err"
  local rc=$?
  set -e

  rm -rf "$workdir"
  echo "exit_code: $rc" >> "$prov"

  if [ $rc -ne 0 ]; then
    echo "extraction: skipped (process failed)" >> "$prov"
    return $rc
  fi

  # The CLI wraps the schema-validated object in a result envelope; the merge consumes plain
  # critique objects, so the unwrapping happens here, next to the invocation that produced it.
  # Anything unexpected in the envelope fails the lens loudly instead of merging an empty result.
  set +e
  "$PY" - "$raw" "$out" <<'PY'
import json, sys
try:
    envelope = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    sys.stderr.write(f"unparseable CLI envelope: {exc}\n"); sys.exit(3)
if envelope.get("is_error"):
    sys.stderr.write(f"CLI reported an error result: {envelope.get('subtype')} "
                     f"{envelope.get('api_error_status')}\n"); sys.exit(4)
critique = envelope.get("structured_output")
if not isinstance(critique, dict) or "findings" not in critique:
    sys.stderr.write("no structured_output with a findings list in the CLI envelope\n"); sys.exit(5)
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(critique, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"{len(critique['findings'])} finding(s)")
PY
  local erc=$?
  set -e
  echo "extraction_exit_code: $erc" >> "$prov"
  return $erc
}

echo "running $(echo "$LENSES" | wc -w) isolated critics in parallel..."

declare -A PIDS=()
for lens in $LENSES; do
  run_one_lens "$lens" > "$OUTDIR/run-$lens.log" 2>&1 &
  PIDS[$lens]=$!
  echo "  lens '$lens' -> pid ${PIDS[$lens]}"
done

FAILED=""
for lens in $LENSES; do
  if wait "${PIDS[$lens]}"; then
    echo "  lens '$lens': ok"
  else
    echo "  lens '$lens': FAILED (see $OUTDIR/critique-$lens.stderr.txt and $OUTDIR/run-$lens.log)" >&2
    FAILED="$FAILED $lens"
  fi
done

MERGE_ARGS=()
for lens in $LENSES; do
  MERGE_ARGS+=("$lens=$OUTDIR/critique-$lens.json")
done

set +e
"$PY" "$MERGER" "$OUTDIR/critique-merged.json" "${MERGE_ARGS[@]}"
MRC=$?
set -e

echo "merged critique: $OUTDIR/critique-merged.json"
echo "provenance records: $OUTDIR/critique-<lens>.provenance.txt"

if [ -n "$FAILED" ] || [ $MRC -ne 0 ]; then
  echo "plan-critic run INCOMPLETE — failed lens(es):${FAILED:- none}; merge exit $MRC" >&2
  echo "Report this as a failed gate run. Do not treat a partial result as a complete critique." >&2
  exit 1
fi

echo "all lenses completed"
