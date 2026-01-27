from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from tests.cookbook.support import load_recipe

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.mark.unit
@pytest.mark.cookbook
def test_analyze_single_paper_main_async_invokes_frontdoor_and_prints(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_env: Callable[..., dict[str, Any]],
) -> None:
    # Arrange: create a simple text file to serve as input
    p: Path = tmp_path / "doc.txt"
    p.write_text("Hello world. This is a tiny sample.")

    # Fake env returned by frontdoor.run_simple
    async def fake_run_simple(prompt: str, **_kwargs: Any) -> dict[str, Any]:
        assert prompt == "Do something"
        # We don't validate the Source further here; recipes pass it through
        return make_env(
            status="ok", answers=["Result body"], usage={"total_token_count": 42}
        )

    monkeypatch.setattr("pollux.frontdoor.run_simple", fake_run_simple)

    # Act: load the recipe module by path (filename uses dashes)
    ns = load_recipe("cookbook/getting-started/analyze-single-paper.py")
    main_async = ns["main_async"]
    asyncio.run(main_async(p, "Do something"))

    # Assert: output contains key signals
    out = capsys.readouterr().out
    assert "Status: ok" in out
    assert "Answer (first 400 chars):" in out
    assert "Tokens: 42" in out
