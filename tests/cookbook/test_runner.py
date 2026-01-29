from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

import cookbook.__main__ as runner

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
@pytest.mark.cookbook
def test_dotted_spec_resolves_to_hyphenated_path() -> None:
    spec = runner.resolve_spec("production.resume_on_failure")
    assert str(spec.path).endswith("cookbook/production/resume-on-failure.py")


@pytest.mark.unit
@pytest.mark.cookbook
def test_repo_root_path_outside_cookbook_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = runner.main(["src/pollux/frontdoor.py"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Recipe not found" in err


@pytest.mark.unit
@pytest.mark.cookbook
def test_main_runs_recipe_via_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("hello")

    async def fake_run_simple(prompt: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "answers": [f"echo:{prompt}"],
            "usage": {"total_token_count": 1},
        }

    monkeypatch.setattr("pollux.frontdoor.run_simple", fake_run_simple)

    code = runner.main(
        [
            "getting-started/analyze-single-paper.py",
            "--",
            "--input",
            str(f),
            "--prompt",
            "Do it",
        ]
    )
    assert code == 0
