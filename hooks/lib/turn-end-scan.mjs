/**
 * hooks/lib/turn-end-scan.mjs
 *
 * Shared helpers for the two "never end a turn with work still outstanding"
 * hooks:
 *
 *   - hooks/check-developer-background-wait.mjs  (SubagentStop, #93)
 *       the `developer` subagent must not end its turn while the verification
 *       run it backgrounded is unresolved.
 *   - hooks/check-session-turn-end.mjs           (Stop, #23)
 *       the top-level `process-ticket` session must not end its turn while a
 *       command it backgrounded is unresolved, nor while the package's work
 *       sits uncommitted in the worktree.
 *
 * Both hooks answer the same underlying question from a JSONL transcript —
 * "is there a Bash(run_in_background: true) call that nothing has waited on
 * since?" — so the walk lives here once. The two hooks differ only in scope
 * and in what they say when they block, not in how they detect.
 *
 * Every function here is total: it returns a null/empty result rather than
 * throwing, because both callers are fail-safe hooks that must never block a
 * turn because of their own bug.
 */

import { readFileSync } from "node:fs";

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
 * Walk a transcript and report the command of the most recent
 * Bash(run_in_background: true) call that nothing has resolved since.
 *
 * A backgrounded Bash call opens an "unresolved" window; a subsequent
 * `Monitor` call — the sanctioned in-turn wait — closes it. Only the *last*
 * such window matters: anything resolved earlier in the transcript is not the
 * failure these hooks exist to catch.
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

      if (
        item.name === "Bash" &&
        item.input &&
        item.input.run_in_background === true
      ) {
        unresolved = String(item.input.command ?? "(unknown command)");
        continue;
      }

      if (item.name === "Monitor") {
        unresolved = null;
        continue;
      }
    }
  }

  return unresolved;
}

/**
 * Emit a block decision and exit. Hooks block by writing
 * {"decision":"block","reason":"..."} to stdout and exiting 0.
 *
 * @param {string} reason
 * @returns {never}
 */
export function block(reason) {
  process.stdout.write(JSON.stringify({ decision: "block", reason }));
  process.exit(0);
}
