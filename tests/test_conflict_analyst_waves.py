"""
Regression tests for ticket #62: conflict-analyst returns an ordered `waves`
array instead of a single flat `parallel` array.

Root cause / rework: orchestrate-tickets is being reworked into a wave-based
fleet model. The conflict-analyst already computed `min_wave_width` and
`dag_depth` internally for the `fit` block, but only ever exposed a single
selected `parallel` set. The orchestrator now needs the full DAG-layering —
an ordered list of parallel-safe sets — so it can run multiple waves
sequentially instead of stopping after one set.

`deferred` (with file-collision/logical-dependency type tagging) and the
`fit` block are retained unchanged.

Red→green: these tests fail against the pre-rework agents/conflict-analyst.md
(single `parallel` array, no `waves` key) and pass after the rework.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ANALYST_MD = REPO_ROOT / "agents" / "conflict-analyst.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_json_block(text: str) -> str:
    """
    Return the LAST fenced ```json block in the file.

    The prose body contains an inline mention of "a single fenced ```json"
    (describing the convention itself) before the actual schema block, so a
    naive first-match non-greedy search grabs the prose gap between that
    inline mention and the real fence. Taking the last match of a
    properly-closed ```json ... ``` block sidesteps that.
    """
    matches = list(re.finditer(r"```json\n(.*?)\n```(?!json)", text, re.DOTALL))
    assert matches, "conflict-analyst.md must contain a fenced ```json block"
    return matches[-1].group(1)


# ---------------------------------------------------------------------------
# Group 1 — waves array replaces parallel as the selected-set key
# ---------------------------------------------------------------------------


def test_json_schema_has_waves_key():
    text = _read(ANALYST_MD)
    block = _extract_json_block(text)
    assert '"waves"' in block, (
        "conflict-analyst.md's JSON schema example must contain a top-level "
        "'waves' key (an ordered array of parallel-safe sets)"
    )


def test_json_schema_waves_is_array_of_arrays():
    """waves must be an ordered list of parallel-safe SETS (array of arrays)."""
    text = _read(ANALYST_MD)
    block = _extract_json_block(text)
    m = re.search(r'"waves"\s*:\s*(\[.*?\n\s*\])', block, re.DOTALL)
    assert m, "'waves' value must be a JSON array in the schema example"
    waves_value = m.group(1)
    # Each wave is itself an array of ticket-entry objects -> expect nested '['
    assert waves_value.count("[") >= 2, (
        "'waves' must be an array of arrays (one array per wave), "
        f"got: {waves_value}"
    )


def test_json_schema_no_longer_has_bare_parallel_key():
    """
    REGRESSION ANCHOR: the flat top-level 'parallel' key must be gone from the
    schema — replaced by 'waves'. (The word 'parallel' may still appear in
    prose describing parallel-safety; only the JSON *key* is checked here.)
    """
    text = _read(ANALYST_MD)
    block = _extract_json_block(text)
    assert '"parallel"' not in block, (
        "conflict-analyst.md's JSON schema example must NOT contain a "
        "top-level '\"parallel\"' key any more — replaced by 'waves'. "
        f"Found in block:\n{block}"
    )


def test_ticket_entry_shape_retained_in_waves():
    """Each wave element keeps the existing parallel-entry shape."""
    text = _read(ANALYST_MD)
    block = _extract_json_block(text)
    for key in ('"ticket"', '"branch"', '"title"', '"files"', '"scope"'):
        assert key in block, (
            f"conflict-analyst.md's JSON schema example must retain the {key} "
            "field on wave entries (existing parallel-entry shape)"
        )


# ---------------------------------------------------------------------------
# Group 2 — wave-building rules documented in prose
# ---------------------------------------------------------------------------


def test_body_describes_wave_0_no_unmet_deps():
    text = _read(ANALYST_MD)
    lower = text.lower()
    assert "waves[0]" in text or "wave 0" in lower, (
        "conflict-analyst.md must describe wave 0 (no unmet deps + disjoint "
        "footprints)"
    )


def test_body_describes_wave_1_depends_on_wave_0():
    text = _read(ANALYST_MD)
    assert "waves[1]" in text or "wave 1" in text.lower(), (
        "conflict-analyst.md must describe wave 1 (deps only in wave 0, "
        "disjoint within itself)"
    )


def test_body_describes_dag_layering():
    text = _read(ANALYST_MD)
    assert "DAG" in text, (
        "conflict-analyst.md must reference DAG-layering as the basis for "
        "the ordered waves array"
    )


# ---------------------------------------------------------------------------
# Group 3 — deferred + fit block retained unchanged
# ---------------------------------------------------------------------------


def test_deferred_key_retained():
    text = _read(ANALYST_MD)
    block = _extract_json_block(text)
    assert '"deferred"' in block, (
        "conflict-analyst.md's JSON schema example must retain the "
        "'deferred' key"
    )


def test_deferred_type_tagging_retained():
    text = _read(ANALYST_MD)
    assert "file-collision" in text and "logical-dependency" in text, (
        "conflict-analyst.md must retain the file-collision / "
        "logical-dependency type tagging on deferred entries"
    )


def test_fit_block_retained():
    text = _read(ANALYST_MD)
    block = _extract_json_block(text)
    assert '"fit"' in block, (
        "conflict-analyst.md's JSON schema example must retain the top-level "
        "'fit' key"
    )


def test_fit_block_signals_retained():
    text = _read(ANALYST_MD)
    for signal in ("dag_depth", "min_wave_width", "cross_wave_shared_files",
                   "ticket_count", "verdict"):
        assert signal in text, (
            f"conflict-analyst.md must retain the '{signal}' fit signal"
        )
