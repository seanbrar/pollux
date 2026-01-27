from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pollux.research.efficiency import EfficiencyReport
from tests.cookbook.support import load_recipe_module


@pytest.mark.unit
@pytest.mark.cookbook
def test_system_instructions_prints_summary_and_env(tmp_path, capsys):
    mod: Any = load_recipe_module(
        "cookbook/research-workflows/system-instructions-with-research-helper.py"
    )

    # Build a minimal EfficiencyReport with expected env fields
    rep = EfficiencyReport(
        status="ok",
        vectorized={"answers": ["x"], "metrics": {"durations": {}}},
        naive=({"answers": ["y"], "metrics": {"durations": {}}},),
        vec_tokens=10,
        vec_time_s=0.1,
        vec_requests=1,
        naive_tokens=20,
        naive_time_s=0.2,
        naive_requests=3,
        tokens_ratio=2.0,
        time_ratio=2.0,
        call_ratio=3.0,
        prompt_count=3,
        source_count=2,
        env={
            "mode": "aggregate",
            "prefer_json_effective": True,
            "aggregate_expected_answer_count": 3,
            "aggregate_observed_answer_count": 3,
        },
        vec_mode="aggregate",
        label="cookbook-system-instructions",
    )

    async def fake_compare_efficiency(*_args, **_kwargs):
        return rep

    mod.compare_efficiency = fake_compare_efficiency

    # Act
    asyncio.run(
        mod.run_with_system(
            directory=Path(tmp_path),
            mode="aggregate",
            trials=2,
            system="You are concise.",
            builder=mod.default_aggregate_prompt_builder,
        )
    )

    # Assert
    out = capsys.readouterr().out
    assert "System prompt in effect" in out
    assert "Efficiency Summary" in out
    assert "Env snapshot" in out
    assert "prefer_json_effective" in out
    assert "aggregate_expected_answer_count" in out
