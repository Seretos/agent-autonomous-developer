#!/usr/bin/env python3
"""
Tells a gate round that found something NEW apart from one that only repeats
what an earlier round in the same generation already found.

Deliberately mechanical, same philosophy as plan-critic-merge.py: no model in
the loop, no judgment call about whether a finding is "really" the same one —
only a fixed, quoted fingerprint compared for exact equality. Placing a model
here would make this script a curator, able to wave a stagnating round
through as "progress" on its own opinion; that is precisely what
process-ticket's round-cap decision (see skills/process-ticket/SKILL.md,
"Round caps: progress or stagnation") must not be exposed to.

Fingerprint rules, by gate:

  * plan-critic / test-critic findings: fingerprint is the exact pair
    (kind, violated_criterion), taken only from findings at severity
    "critical" or "major" AND finding_class "blocking" (ticket #105) — a
    "minor" finding is real feedback but not something a stagnation check
    should key on, matching how skills/process-ticket/SKILL.md already
    treats "minor" as non-blocking; a "note"-class finding (the plan-critic
    untestable/simplifier lenses) is excluded for the same reason a "minor"
    is: it is never itself a reason for another round, so it must not count
    as "progress" that buys one. Without this filter, a monotonically
    growing plan produces a fresh simplifier finding every round — a new
    fingerprint every time — and the loop would run to the hard cap on an
    unchanged critical purely on the back of note-class churn. A finding
    with no finding_class (any gate/input predating this field) defaults to
    "blocking", so test-critic and review — which never emit note-class
    findings — are unaffected.
  * review findings (the reviewer's additive structured block — see
    agents/reviewer.md, "What you return"): fingerprint is
    (kind, file, what[:80]), taken only from findings at severity
    "blocking". A reviewer has no violated_criterion to quote (no
    requirement IDs to anchor to), so the fingerprint is coarser by
    necessity; that is documented, not a bug to be tightened here.

The history file is a flat JSON list of `[kind, key]` pairs already seen in
the current generation. This script never resets it — that is
process-ticket's job on a replan (a new generation starts from an empty
history, deliberately: a fresh plan deserves a fresh stagnation comparison).
This script only ever reads it, decides, and appends the current round's new
fingerprints to it.

Usage:
    stagnation-check.py <gate> <findings-json> <history-json>

  <gate>           one of: plan-critic, test-critic, review
  <findings-json>  path to this round's findings JSON — for plan-critic/
                    test-critic, a critique-merged.json (or any JSON with a
                    top-level "findings" list in that shape); for review, the
                    reviewer's structured findings block, saved to a file by
                    the caller first.
  <history-json>   path to the generation's fingerprint history. Created
                    empty ("[]") if it does not exist yet. Updated in place
                    with this round's new fingerprints on exit, regardless of
                    the verdict — a "stagnation" round still recorded nothing
                    new, and there is nothing to fold in.

Prints exactly one line to stdout: "RESULT: progress" or "RESULT: stagnation".
Exit code 0 on either verdict; exit code 2 on a usage/input error (never
silently defaults to a verdict on bad input, since a wrong default here is
a wrong decision about a human's Question card).
"""
import json
import sys

GATE_RULES = {
    "plan-critic": {"severities": {"critical", "major"}, "keyed_on": "violated_criterion"},
    "test-critic": {"severities": {"critical", "major"}, "keyed_on": "violated_criterion"},
    "review": {"severities": {"blocking"}, "keyed_on": "file+what"},
}


def _fingerprint(gate, finding):
    kind = finding.get("kind", "")
    if GATE_RULES[gate]["keyed_on"] == "violated_criterion":
        key = finding.get("violated_criterion", "")
    else:
        what = (finding.get("what") or "")[:80]
        key = f"{finding.get('file', '')}::{what}"
    return [kind, key]


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def main(argv):
    if len(argv) != 4:
        sys.stderr.write(
            "usage: stagnation-check.py <plan-critic|test-critic|review> "
            "<findings-json> <history-json>\n")
        return 2

    gate, findings_path, history_path = argv[1], argv[2], argv[3]
    if gate not in GATE_RULES:
        sys.stderr.write(f"unknown gate {gate!r}; expected one of {sorted(GATE_RULES)}\n")
        return 2

    try:
        payload = _load_json(findings_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        sys.stderr.write(f"could not read findings from {findings_path}: {e}\n")
        return 2

    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        sys.stderr.write(f"{findings_path}: 'findings' is not a list\n")
        return 2

    severities = GATE_RULES[gate]["severities"]
    current = [
        _fingerprint(gate, f) for f in findings
        if f.get("severity") in severities
        # finding_class only exists on plan-critic/test-critic findings (stamped by
        # plan-critic-merge.py); a review finding has no such field and is never note-class, so the
        # default keeps it counted exactly as before this filter existed.
        and f.get("finding_class", "blocking") == "blocking"
    ]

    history = _load_json(history_path, default=[])
    if not isinstance(history, list):
        sys.stderr.write(f"{history_path}: expected a JSON list\n")
        return 2
    seen = {tuple(fp) for fp in history}

    new_fingerprints = [fp for fp in current if tuple(fp) not in seen]

    updated = history + new_fingerprints
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)

    print(f"RESULT: {'progress' if new_fingerprints else 'stagnation'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
