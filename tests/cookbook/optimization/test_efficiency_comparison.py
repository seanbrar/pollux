from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.cookbook.support import load_recipe


@pytest.mark.unit
@pytest.mark.cookbook
def test_efficiency_comparison_main_async_prints_summary_and_env(
    tmp_path, capsys, monkeypatch
):
    # Arrange: create two small files to be picked up by the recipe
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("beta")

    # Build a minimal EfficiencyReport to return from the research helper
    from pollux.research.efficiency import EfficiencyReport

    report = EfficiencyReport(
        status="ok",
        vectorized={"answers": ["x"], "metrics": {"durations": {}}},
        naive=({"answers": ["y"], "metrics": {"durations": {}}},),
        vec_tokens=10,
        vec_time_s=0.1,
        vec_requests=1,
        naive_tokens=20,
        naive_time_s=0.3,
        naive_requests=3,
        tokens_ratio=2.0,
        time_ratio=3.0,
        call_ratio=3.0,
        prompt_count=3,
        source_count=2,
        env={"foo": "bar"},
        vec_mode="aggregate",
    )

    async def fake_compare_efficiency(*_args, **_kwargs):
        return report

    monkeypatch.setattr(
        "pollux.research.compare_efficiency", fake_compare_efficiency
    )

    # Act: load the recipe module by path (filenames use dashes)
    ns = load_recipe("cookbook/optimization/efficiency-comparison.py")
    main_async = ns["main_async"]
    asyncio.run(main_async(Path(tmp_path), mode="aggregate", trials=2))

    # Assert
    out = capsys.readouterr().out
    assert "Efficiency Summary:" in out
    # summary() content should be printed
    assert "prompts=" in out and "sources=" in out
    assert "Env:" in out and "foo" in out and "bar" in out
