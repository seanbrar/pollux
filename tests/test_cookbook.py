"""Cookbook boundary tests.

Tests for the cookbook runner CLI—the boundary between user commands
and recipe execution.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# Ensure project root is in path for cookbook import
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import cookbook.__main__ as runner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.cookbook]


class TestCookbookRunner:
    """Tests for the cookbook CLI runner."""

    def test_dotted_spec_resolves_to_hyphenated_path(self) -> None:
        """Dotted spec 'a.b_c' resolves to 'a/b-c.py' path."""
        spec = runner.resolve_spec("production.resume_on_failure")
        assert str(spec.path).endswith("cookbook/production/resume-on-failure.py")

    def test_repo_root_path_outside_cookbook_is_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Paths outside cookbook directory are rejected."""
        code = runner.main(["src/pollux/frontdoor.py"])
        assert code == 2
        err = capsys.readouterr().err
        assert "Recipe not found" in err

    def test_main_runs_recipe_via_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLI successfully runs a recipe with mocked execution."""
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
