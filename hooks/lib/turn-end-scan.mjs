/**
 * hooks/lib/turn-end-scan.mjs
 *
 * Shared helpers for the three "nothing ever runs in the background" hooks:
 *
 *   - hooks/check-no-background.mjs               (PreToolUse, #101)
 *       refuses the call before it happens: Bash(run_in_background: true),
 *       a Bash command that detaches (`nohup … &`, `Start-Job`,
 *       `Start-Process`, trailing `&`), and every `Monitor` call.
 *   - hooks/check-developer-background-wait.mjs   (SubagentStop, #93)
 *       the `developer` subagent must not end its turn while a command it
 *       backgrounded is unresolved.
 *   - hooks/check-session-turn-end.mjs            (Stop, #23)
 *       the top-level `process-ticket` session must not end its turn while a
 *       command it backgrounded is unresolved, nor while the package's work
 *       sits uncommitted in the worktree.
 *
 * All three answer the same question — "is this a backgrounded command?" —
 * so the classifier lives here once, and the two turn-end hooks share one
 * transcript walk on top of it.
 *
 * ## Why `Monitor` no longer resolves anything (#101)
 *
 * Until #101 the walk treated a later `Monitor` call as the sanctioned
 * in-turn wait that "closed" a backgrounded command. The live incident
 * `agent-worktree#176` (attempt 1) showed that this is exactly the shape
 * that kills a headless session: the developer backgrounded the suite,
 * armed a `Monitor`, and ended its turn — the hook saw the `Monitor`, said
 * nothing, and the process died with the suite. A `Monitor` is not a wait;
 * it is a promise to be woken, and nothing wakes a headless session. So a
 * backgrounded command is now unresolved for the rest of the transcript.
 * The only thing that does resolve it is the PreToolUse hook having refused
 * it in the first place, recognised by the marker it leaves in the
 * transcript (see NO_BACKGROUND_MARKER) — then nothing is running, and
 * blocking the stop would only trap the agent behind a call it cannot undo.
 *
 * Every function here is total: it returns a null/empty result rather than
 * throwing, because every caller is a fail-safe hook that must never block a
 * turn because of its own bug.
 */

import { readFileSync } from "node:fs";

/**
 * Token the PreToolUse hook puts into its refusal text. When it appears in
 * the transcript after a backgrounded call, that call never ran.
 */
export const NO_BACKGROUND_MARKER = "[adev-no-background]";

/**
 * Bash command shapes that detach work from the calling turn, independent of
 * the `run_in_background` flag:
 *   - `nohup …`                      POSIX detach
 *   - `Start-Job` / `Start-Process`  PowerShell detach
 *   - a trailing `&` (end of command, or before `;` / newline) — the plain
 *     shell background operator. `&&` and `2>&1` do not match: the `&` must
 *     not be preceded by another `&` or by `>`, and must be followed only by
 *     whitespace, `;`, a newline, or the end of the command.
 */
const DETACH_PATTERNS = [
  /(^|[\s;|&(])nohup(\s|$)/,
  /(^|[\s;|&({])Start-Job(\s|$)/i,
  /(^|[\s;|&({])Start-Process(\s|$)/i,
  /(^|[^&>])&\s*(?=$|;|\n)/,
];

/**
 * Classify a Bash tool input. Returns a short reason when the call would
 * run something in the background, null when it is an ordinary foreground
 * call.
 *
 * @param {unknown} input  the `input` object of a Bash tool_use block
 * @returns {string | null}
 */
export function backgroundReasonForBash(input) {
  if (!input || typeof input !== "object") return null;
  if (input.run_in_background === true) return "run_in_background: true";
  const command = typeof input.command === "string" ? input.command : "";
  if (!command) return null;
  if (DETACH_PATTERNS[0].test(command)) return "nohup";
  if (DETACH_PATTERNS[1].test(command)) return "Start-Job";
  if (DETACH_PATTERNS[2].test(command)) return "Start-Process";
  if (DETACH_PATTERNS[3].test(command)) return "trailing `&`";
  return null;
}

/**
 * The agent-name segment of a hook payload's `agent_type`.
 *
 * Plain substring matching is unsafe in this plugin: its id is
 * "agent-autonomous-developer", so every agent_type here
 * ("agent-autonomous-developer:reviewer", "...:planner", ...) contains
 * "developer" as a substring of the *plugin* name. Match the segment after
 * the last ":" (or the whole string when unprefixed) instead.
 *
 * @param {unknown} agentType
 * @returns {string}
 */
export function agentNameOf(agentType) {
  const s = String(agentType ?? "");
  return s.includes(":") ? s.slice(s.lastIndexOf(":") + 1) : s;
}

/**
 * Read a JSONL transcript into lines.
 *
 * @param {unknown} transcriptPath
 * @returns {string[] | null} lines, or null when the path is missing or unreadable
 */
export function readTranscriptLines(transcriptPath) {
  if (!transcriptPath) return null;
  try {
    return readFileSync(String(transcriptPath), "utf8").split(/\r?\n/);
  } catch {
    return null;
  }
}

/**
 * Walk a transcript and report the command of the most recent backgrounded
 * Bash call (see backgroundReasonForBash) that actually ran — i.e. that the
 * PreToolUse hook did not refuse.
 *
 * A `Monitor` call does NOT resolve it (#101, see the file header). The
 * refusal marker does: a line after the call that carries
 * NO_BACKGROUND_MARKER means the harness rejected it and nothing is running.
 * Only the *last* backgrounded call matters: anything refused earlier in the
 * transcript is not the failure these hooks exist to catch.
 *
 * @param {string[] | null} lines
 * @returns {string | null} the unresolved command, or null when there is none
 */
export function unresolvedBackgroundCommand(lines) {
  if (!Array.isArray(lines)) return null;

  let unresolved = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch {
      continue;
    }

    // The PreToolUse refusal shows up in whatever record the harness writes
    // for a denied call (tool_result, system line, …) — never in an
    // assistant record, which is where a tool_use that merely *mentions* the
    // marker (an edit to this very file) would live. Match the marker on the
    // raw line so the exact record shape does not matter.
    if (
      unresolved !== null &&
      parsed?.type !== "assistant" &&
      line.includes(NO_BACKGROUND_MARKER)
    ) {
      unresolved = null;
      continue;
    }

    // Top-level transcripts nest the blocks under `message.content`; subagent
    // transcripts put them directly on `content`. Accept both so one walk
    // serves both hooks.
    const content = Array.isArray(parsed.content)
      ? parsed.content
      : Array.isArray(parsed?.message?.content)
        ? parsed.message.content
        : null;
    if (!content) continue;

    for (const item of content) {
      if (!item || item.type !== "tool_use") continue;
      if (item.name !== "Bash") continue;
      if (backgroundReasonForBash(item.input) === null) continue;
      unresolved = String(item.input.command ?? "(unknown command)");
    }
  }

  return unresolved;
}

/**
 * Emit a block decision and exit. Stop/SubagentStop hooks block by writing
 * {"decision":"block","reason":"..."} to stdout and exiting 0.
 *
 * @param {string} reason
 * @returns {never}
 */
export function block(reason) {
  process.stdout.write(JSON.stringify({ decision: "block", reason }));
  process.exit(0);
}
