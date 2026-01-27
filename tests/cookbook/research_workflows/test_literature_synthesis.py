from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.cookbook.support import load_recipe


@pytest.mark.unit
@pytest.mark.cookbook
def test_literature_synthesis_main_async_prints_structured_summary(
    tmp_path, capsys, monkeypatch
):
    # Arrange: create a couple of simple text files
    (tmp_path / "one.txt").write_text("Paper one content")
    (tmp_path / "two.txt").write_text("Paper two content")

    # Fake run_batch to return a final answer that matches the expected schema
    synth_obj = {
        "executive_summary": "This is the executive summary.",
        "key_methodologies": ["Method A", "Method B"],
        "main_findings": ["Finding 1"],
        "research_gaps": ["Gap"],
        "future_directions": ["Future"],
        "practical_implications": ["Implication"],
    }
    payload = {"answers": [json.dumps(synth_obj)]}

    async def fake_run_batch(*_args, **_kwargs):
        return payload

    monkeypatch.setattr("pollux.frontdoor.run_batch", fake_run_batch)

    # Act: load the recipe module by path (filename uses dashes)
    ns = load_recipe("cookbook/research-workflows/literature-synthesis.py")
    main_async = ns["main_async"]
    asyncio.run(main_async(Path(tmp_path)))

    # Assert: ensure the structured flow is detected and summarized
    out = capsys.readouterr().out
    assert "Literature synthesis complete!" in out
    assert "Executive Summary" in out
    assert "Key Methodologies" in out
