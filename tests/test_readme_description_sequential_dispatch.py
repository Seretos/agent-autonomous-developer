"""
Regression tests for ticket #88 (reviewer fix round 2, findings 3 and 4):
README.md and description.md were never touched by any prior round of this
ticket's fix loop, and both still described wave-member dispatch as
happening "in parallel"/"concurrently" — stale since ticket #88 made
`orchestrate-tickets` Phase C dispatch wave members SEQUENTIALLY, one fresh
synchronous unnamed spawn at a time, specifically to eliminate the
background/named-spawn mailbox-delivery report loss that caused repeated
silent stalls in production.

Both files are marketing/user-facing docs (README.md the repo README,
description.md the marketplace listing), so a reader trusting either would
come away with an incorrect mental model of how the fleet actually executes.

Scope note: this is intentionally narrow to claims about concurrent/parallel
*dispatch or execution* of wave members. It must NOT flag "parallel-safe
waves"/"parallel-safe sets" — that phrase describes the conflict-analyst's
file-collision/dependency DAG-layering property (which tickets CAN safely
coexist in one wave), which remains true and unrelated to how those tickets
are actually executed once selected.

Red -> green: these tests fail against the pre-fix README.md/description.md
(which claim parallel/concurrent wave-member dispatch) and pass once both
files are reworded to describe sequential dispatch, without touching the
still-accurate "parallel-safe wave(s)" phrasing.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
README_MD = REPO_ROOT / "README.md"
DESCRIPTION_MD = REPO_ROOT / "description.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------


def test_readme_intro_does_not_claim_parallel_backlog_dispatch():
    n = _normalize(_read(README_MD))
    assert "dispatched in parallel across isolated git worktrees" not in n, (
        "README.md's intro must not claim the backlog is 'dispatched in "
        "parallel across isolated git worktrees' -- ticket #88 made "
        "wave-member dispatch sequential"
    )


def test_readme_wave_walkthrough_does_not_claim_parallel_process_ticket_runs():
    n = _normalize(_read(README_MD))
    assert not re.search(
        r"runs\s+`process-ticket\(mode=integration\)`\s+\*\*in parallel\*\*",
        n,
    ), (
        "README.md's wave-run walkthrough step 3 must not claim "
        "process-ticket(mode=integration) runs 'in parallel' across a "
        "wave's members -- ticket #88 made this sequential"
    )
    # The walkthrough should instead describe sequential dispatch.
    assert re.search(r"sequential", n, re.IGNORECASE), (
        "README.md's wave-run walkthrough should describe wave-member "
        "dispatch as sequential"
    )


def test_readme_parallel_safe_wave_layering_language_untouched():
    """Guard against an over-broad fix: 'parallel-safe wave(s)' describes the
    conflict-analyst's file-collision/dependency layering property, not
    execution, and must remain."""
    n = _normalize(_read(README_MD))
    assert re.search(r"parallel-safe\s+\*{0,2}waves?", n, re.IGNORECASE), (
        "README.md must still describe the conflict-analyst's output as "
        "'parallel-safe waves' -- that phrasing is accurate and must not be "
        "removed by this fix"
    )


# ---------------------------------------------------------------------------
# description.md
# ---------------------------------------------------------------------------


def test_description_intro_does_not_claim_parallel_dispatch():
    n = _normalize(_read(DESCRIPTION_MD))
    assert "dispatch an entire backlog in parallel across isolated git worktrees" not in n, (
        "description.md's intro must not claim it can 'dispatch an entire "
        "backlog in parallel across isolated git worktrees' -- ticket #88 "
        "made wave-member dispatch sequential"
    )


def test_description_capability_bullet_not_labeled_parallel_dispatch():
    n = _normalize(_read(DESCRIPTION_MD))
    assert "**Parallel backlog dispatch**" not in n, (
        "description.md must not label a capability bullet 'Parallel "
        "backlog dispatch' -- ticket #88 made wave-member dispatch "
        "sequential"
    )
    assert "concurrently without interfering" not in n, (
        "description.md must not claim multiple tickets 'proceed "
        "concurrently without interfering' -- ticket #88 made wave-member "
        "dispatch sequential"
    )
