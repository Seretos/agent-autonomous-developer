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

import { readFileSync } from "node:fs";
import process from "node:process";

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
  // substring of the *plugin* name, not the agent name. Match the agent-name
  // segment (after the last ":", or the whole string when unprefixed)
  // exactly instead.
  const agentType = String(payload.agent_type ?? "");
  const agentName = agentType.includes(":")
    ? agentType.slice(agentType.lastIndexOf(":") + 1)
    : agentType;
  if (agentName !== "developer") {
    process.exit(0);
  }

  // --- 3. Resolve the transcript path ---
  const transcriptPath =
    payload.agent_transcript_path ?? payload.transcript_path ?? null;
  if (!transcriptPath) {
    process.exit(0);
  }

  // --- 4. Read and scan the JSONL transcript ---
  let lines;
  try {
    const content = readFileSync(transcriptPath, "utf8");
    lines = content.split(/\r?\n/);
  } catch {
    // Unreadable transcript — fail-safe, do not block.
    process.exit(0);
  }

  // Walk the transcript in order. A backgrounded Bash call opens an
  // "unresolved" window; a subsequent Monitor call closes it. Only the
  // *last* backgrounded Bash call matters — anything resolved earlier in
  // the transcript is not the failure this hook exists to catch.
  let unresolvedBgCommand = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch {
      // Skip malformed JSONL lines.
      continue;
    }

    if (!Array.isArray(parsed.content)) continue;

    for (const item of parsed.content) {
      if (!item || item.type !== "tool_use") continue;

      if (
        item.name === "Bash" &&
        item.input &&
        item.input.run_in_background === true
      ) {
        unresolvedBgCommand = String(item.input.command ?? "(unknown command)");
        continue;
      }

      if (item.name === "Monitor") {
        unresolvedBgCommand = null;
        continue;
      }
    }
  }

  // --- 5. Decision ---
  if (unresolvedBgCommand) {
    const reason =
      "developer: turn is ending with a backgrounded command still " +
      `unresolved (${unresolvedBgCommand}). This is the ticket #93 ` +
      "anti-pattern: a subagent's turn ending TERMINATES it, it is never " +
      "suspended and resumed, so the backgrounded process is about to be " +
      "killed and any \"I'll resume once it completes\" expectation cannot " +
      "be honored — the caller will only see a hollow success with no real " +
      "verification result. Continue this turn and either (a) wait for the " +
      "command inside this same turn with the Monitor tool — the mandatory " +
      "pattern for the full-suite verification run (agents/developer.md " +
      "step 4) — or (b) finish the change report with an explicit PASS/FAIL " +
      "result instead of leaving a background run outstanding.";
    process.stdout.write(JSON.stringify({ decision: "block", reason }));
    process.exit(0);
  }

  process.exit(0);
}

main().catch(() => {
  // Any unexpected error — fail-safe, do not block.
  process.exit(0);
});
