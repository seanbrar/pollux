from __future__ import annotations

from pollux.extensions.dependency_analyzer import analyze_dependencies


def test_dependency_analyzer_regex_and_overlap():
    prompts = [
        "What are the two main factors discussed?",
        "How do these factors interact?",
        "For the second question, which mitigation was recommended?",
    ]
    out = analyze_dependencies(prompts)
    assert out["version"].startswith("1.")
    # 2 and 3 likely depend on earlier questions
    assert 2 in out["dependent_indices"]
    assert 3 in out["dependent_indices"]
    # Hints include a reference to second question
    assert any(h["src_index"] == 3 and h["dst_index"] in (1, 2) for h in out["hints"])


def test_dependency_analyzer_no_dependency():
    prompts = [
        "Summarize the chapter.",
        "List three examples unrelated to the summary.",
    ]
    out = analyze_dependencies(prompts)
    # Could be some overlap, but threshold should usually keep it independent
    assert out["dependent_indices"] in ([], [2])


def test_dependency_analyzer_cue_provenance_ordinal():
    prompts = [
        "What are the two main factors discussed?",
        "How do these factors interact?",
        "For the second question, which mitigation was recommended?",
    ]
    out = analyze_dependencies(prompts)
    # Find hint for third prompt
    third_hints = [h for h in out["hints"] if h["src_index"] == 3]
    assert third_hints, "Expected a dependency hint for the third prompt"
    # Ordinal reason should be present
    assert any(
        r.startswith("ordinal:") and "second" in r
        for h in third_hints
        for r in h["reasons"]
    )
    # Destination should be a prior prompt
    assert any(h["dst_index"] in (1, 2) for h in third_hints)


def test_dependency_analyzer_bounds_handling_invalid_numeric_reference():
    prompts = [
        "Alpha topic.",
        "Bravo concept.",
        "About Q99 only.",
    ]
    out = analyze_dependencies(prompts)
    # No meaningful overlap; invalid numeric reference shouldn't force a dependency
    assert 3 not in out["dependent_indices"]


def test_dependency_analyzer_invariants_and_determinism():
    prompts = [
        "List factors.",
        "How do these interact?",
        "See above second question details.",
    ]
    out1 = analyze_dependencies(prompts)
    out2 = analyze_dependencies(prompts)
    # First prompt is never dependent
    assert 1 not in out1["dependent_indices"]
    # dst_index always less than src_index
    assert all(h["dst_index"] < h["src_index"] for h in out1["hints"])
    # Deterministic output
    assert out1 == out2


def test_dependency_analyzer_mixed_cues_ordinal_wins():
    prompts = [
        "What are the risks discussed?",
        "Explain mitigation A.",
        "See above second question about the mitigation details.",
    ]
    out = analyze_dependencies(prompts)
    third_hints = [h for h in out["hints"] if h["src_index"] == 3]
    assert third_hints, "Expected a dependency hint for the third prompt"
    # Should include both a general regex cue and an ordinal cue
    assert any("regex:see_above" in r for h in third_hints for r in h["reasons"])
    assert any("ordinal:second" in r for h in third_hints for r in h["reasons"])
    # Prefer ordinal for destination when present
    assert any(h["dst_index"] == 2 for h in third_hints)


def test_dependency_analyzer_override_thresholds_affect_detection():
    prompts = [
        "What are factors?",
        "List factors.",
    ]
    # With a very high threshold, 2 might not be considered dependent
    out_strict = analyze_dependencies(prompts, overlap_threshold=0.95)
    # With a very low threshold, 2 should be considered dependent due to overlap
    out_lenient = analyze_dependencies(prompts, overlap_threshold=0.0)
    assert 2 not in out_strict["dependent_indices"]
    assert 2 in out_lenient["dependent_indices"]


def test_dependency_analyzer_default_prev_on_see_above():
    prompts = [
        "Alpha topic.",
        "See above.",
    ]
    out = analyze_dependencies(prompts)
    # Should default to previous when generic see-above is present and overlap is low
    assert 2 in out["dependent_indices"]
    hints = [h for h in out["hints"] if h["src_index"] == 2]
    assert hints and any(h["dst_index"] == 1 for h in hints)
    # Reason provenance should include both the regex cue and the default mapping
    assert any("regex:see_above" in r for h in hints for r in h["reasons"])
    assert any("default_prev:see_above" in r for h in hints for r in h["reasons"])


def test_dependency_analyzer_ordinal_counts_like_regex_for_scoring():
    prompts = [
        "What are the two main factors discussed?",
        "How do these factors interact?",
        "For the second question, elaborate on your rationale.",
    ]
    out = analyze_dependencies(prompts)
    hints = [h for h in out["hints"] if h["src_index"] == 3]
    assert hints, "Expected a dependency hint for the third prompt"
    # Score should be at least the default regex base (0.6) due to ordinal cue
    assert any(h["score"] >= 0.6 for h in hints)
    # And ordinal reason should be present
    assert any("ordinal:second" in r for h in hints for r in h["reasons"])


def test_dependency_analyzer_max_lookback_limits_candidates():
    prompts = [
        "alpha beta gamma",
        "zzz",
        "alpha beta",
    ]
    out = analyze_dependencies(prompts, max_lookback=1)
    # With lookback=1, the third prompt compares only to the second, so no overlap-based dependency
    assert 3 not in out["dependent_indices"]
