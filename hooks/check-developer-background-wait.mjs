/**
 * hooks/check-developer-background-wait.mjs
 *
 * SubagentStop hook: blocks the `developer` subagent from ending its turn
 * while a command it backgrounded via Bash(run_in_background: true) — e.g.
 * the mandatory full-suite verification run — is still unresolved (ticket
 * #93).
 *
 * A subagent's turn ending does not suspend it, it TERMINATES it: the
 * harness kills any background command the subagent started, and the
 * outer process then reports a hollow "success" even though no real
 * verification result was ever produced. agents/developer.md's Hard Rules
 * already forbid this in prose ("Never end a turn while a command you
 * backgrounded is still running"), but a live incident (#93) showed the
 * model doing exactly that anyway — it started the backgrounded test run
 * and replied "I'll resume once it completes", then ended its turn. This
 * hook is the mechanical backstop: it does not trust compliance with the
 * prose rule, it detects the anti-pattern directly from the transcript and
 * blocks the stop so the subagent is forced to actually wait (Monitor) or
 * report a real PASS/FAIL instead.
 *
 * The same mistake one level up — the top-level `process-ticket` session
 * ending its turn with an outstanding background command, which in headless
 * `claude -p` ends the whole process — is caught by the Stop hook
 * hooks/check-session-turn-end.mjs (ticket #23). The transcript walk both
 * hooks need lives in lib/turn-end-scan.mjs.
 *
 * Decision logic:
 *   - Only activates for the "developer" agent (agent_type check).
 *   - Reads the JSONL transcript and walks it in order, tracking whether
 *     the most recently started Bash(run_in_background: true) call has
 *     since been followed by a Monitor tool call (the sanctioned in-turn
 *     wait per agents/developer.md step 4 / Hard Rules).
 *   - If the transcript ends with such a call still unresolved (started,
 *     never Monitor-ed) -> block with a clear message.
 *   - All failure modes (bad stdin, unreadable transcript, wrong agent)
 *     are treated as "do not block" (fail-safe / exit 0), matching the
 *     existing hooks/check-mcp-availability.mjs.
 *
 * Block output: write JSON {"decision":"block","reason":"..."} to stdout, exit 0.
 * Pass: exit 0 with no stdout.
 */

import process from "node:process";

import {
  agentNameOf,
  block,
  readTranscriptLines,
  unresolvedBackgroundCommand,
} from "./lib/turn-end-scan.mjs";

async function main() {
  // --- 1. Read and parse stdin as the hook payload ---
  let payload;
  try {
    const stdinChunks = [];
    for await (const chunk of process.stdin) {
      stdinChunks.push(chunk);
    }
    const raw = Buffer.concat(stdinChunks).toString("utf8");
    payload = JSON.parse(raw);
  } catch {
    // Malformed stdin — fail-safe, do not block.
    process.exit(0);
  }

  // --- 2. Gate on the agent name being exactly "developer" ---
  // Plain substring matching (agentType.includes("developer")) is unsafe
  // here: this plugin's own id is "agent-autonomous-developer", so every
  // agent_type in this plugin ("agent-autonomous-developer:reviewer",
  // "...:planner", "...:context-extractor", ...) contains "developer" as a
  // substring of the *plugin* name, not the agent name. agentNameOf matches
  // the agent-name segment exactly instead.
  if (agentNameOf(payload.agent_type) !== "developer") {
    process.exit(0);
  }

  // --- 3. Read and scan the JSONL transcript ---
  const lines = readTranscriptLines(
    payload.agent_transcript_path ?? payload.transcript_path,
  );
  const unresolvedBgCommand = unresolvedBackgroundCommand(lines);

  // --- 4. Decision ---
  if (unresolvedBgCommand) {
    block(
      "developer: turn is ending with a backgrounded command still " +
        `unresolved (${unresolvedBgCommand}). This is the ticket #93 ` +
        "anti-pattern: a subagent's turn ending TERMINATES it, it is never " +
        "suspended and resumed, so the backgrounded process is about to be " +
        'killed and any "I\'ll resume once it completes" expectation cannot ' +
        "be honored — the caller will only see a hollow success with no real " +
        "verification result. Continue this turn and either (a) wait for the " +
        "command inside this same turn with the Monitor tool — the mandatory " +
        "pattern for the full-suite verification run (agents/developer.md " +
        "step 4) — or (b) finish the change report with an explicit PASS/FAIL " +
        "result instead of leaving a background run outstanding.",
    );
  }

  process.exit(0);
}

main().catch(() => {
  // Any unexpected error — fail-safe, do not block.
  process.exit(0);
});
