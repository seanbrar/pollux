from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest

import cookbook.__main__ as runner

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
@pytest.mark.cookbook
def test_list_shows_known_recipe_and_hides_helpers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = runner.main(["--list"])  # prints to stdout
    assert code == 0
    out = capsys.readouterr().out
    # Shows at least one well-known recipe
    assert "getting-started/analyze-single-paper.py" in out
    # Does not enumerate helper directories
    assert "utils/" not in out
    assert "templates/" not in out
    assert "data/" not in out


@pytest.mark.unit
@pytest.mark.cookbook
def test_dotted_to_path_and_resolve_spec_handles_hyphens() -> None:
    # underscore → hyphen; dotted → slashes
    mapped = runner.dotted_to_path("production.resume_on_failure")
    assert mapped == "production/resume-on-failure.py"

    spec = runner.resolve_spec("production.resume_on_failure")
    # Ensure the resolved file exists and is under cookbook/
    assert spec.path.exists()
    assert str(spec.path).endswith("cookbook/production/resume-on-failure.py")


@pytest.mark.unit
@pytest.mark.cookbook
def test_resolve_spec_accepts_various_forms() -> None:
    # Repo-root style
    spec1 = runner.resolve_spec("cookbook/getting-started/analyze-single-paper.py")
    assert spec1.path.exists()

    # Cookbook-relative
    spec2 = runner.resolve_spec("getting-started/analyze-single-paper.py")
    assert spec2.path.exists()

    # Dotted-like
    spec3 = runner.resolve_spec("getting-started.analyze_single_paper")
    assert spec3.path.exists()


@pytest.mark.unit
@pytest.mark.cookbook
def test_resolve_spec_errors_with_clear_message() -> None:
    with pytest.raises(FileNotFoundError):
        runner.resolve_spec("nope/does_not_exist")


@pytest.mark.unit
@pytest.mark.cookbook
def test_main_runs_recipe_via_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange a small input file and stub the frontdoor to avoid API calls
    f = tmp_path / "doc.txt"
    f.write_text("hello")

    async def fake_run_simple(prompt: str, **_kwargs: Any) -> dict[str, Any]:  # type: ignore[unused-ignore]
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


@pytest.mark.unit
@pytest.mark.cookbook
def test_main_runs_recipe_via_dotted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("hello")

    async def fake_run_simple(prompt: str, **_kwargs: Any) -> dict[str, Any]:  # type: ignore[unused-ignore]
        return {
            "status": "ok",
            "answers": [f"echo:{prompt}"],
            "usage": {"total_token_count": 1},
        }

    monkeypatch.setattr("pollux.frontdoor.run_simple", fake_run_simple)

    code = runner.main(
        [
            "getting-started.analyze_single_paper",
            "--",
            "--input",
            str(f),
        ]
    )
    assert code == 0


@pytest.mark.unit
@pytest.mark.cookbook
def test_main_without_spec_prints_list(capsys: pytest.CaptureFixture[str]) -> None:
    code = runner.main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "Available recipes" in out
    assert "getting-started/analyze-single-paper.py" in out


@pytest.mark.unit
@pytest.mark.cookbook
def test_repo_root_path_outside_cookbook_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Points to a real file in repo but outside cookbook
    code = runner.main(["src/pollux/frontdoor.py"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Recipe not found" in err
    assert "Use --list" in err


@pytest.mark.unit
@pytest.mark.cookbook
def test_errors_print_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    code = runner.main(["nope/does_not_exist"])
    assert code == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "Recipe not found" in out.err


@pytest.mark.unit
@pytest.mark.cookbook
def test_cwd_repo_root_flag_changes_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    import pathlib as _pl

    seen: dict[str, str] = {}

    def fake_run_path(
        _path: str, _run_name: str = "__main__", **_kwargs: Any
    ) -> dict[str, Any]:  # type: ignore[unused-ignore]
        seen["cwd"] = str(_pl.Path.cwd())
        return {}

    monkeypatch.setattr("runpy.run_path", fake_run_path)

    code = runner.main(
        [
            "--cwd-repo-root",
            "getting-started.analyze_single_paper",
        ]
    )
    assert code == 0
    # When flag is on, cwd should be the repo root
    assert seen.get("cwd") == str(runner.repo_root())


@pytest.mark.unit
@pytest.mark.cookbook
def test_no_cwd_repo_root_leaves_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import pathlib as _pl

    seen: dict[str, str] = {}

    def fake_run_path(
        _path: str, _run_name: str = "__main__", **_kwargs: Any
    ) -> dict[str, Any]:  # type: ignore[unused-ignore]
        seen["cwd"] = str(_pl.Path.cwd())
        return {}

    monkeypatch.setattr("runpy.run_path", fake_run_path)
    monkeypatch.chdir(tmp_path)

    code = runner.main(
        [
            "--no-cwd-repo-root",
            "getting-started.analyze_single_paper",
        ]
    )
    assert code == 0
    assert seen.get("cwd") == str(tmp_path)


@pytest.mark.unit
@pytest.mark.cookbook
def test_sys_argv_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    before = list(sys.argv)
    seen: dict[str, list[str]] = {}

    def fake_run_path(
        _path: str, _run_name: str = "__main__", **_kwargs: Any
    ) -> dict[str, Any]:  # type: ignore[unused-ignore]
        seen["argv"] = list(sys.argv)
        return {}

    monkeypatch.setattr("runpy.run_path", fake_run_path)

    code = runner.main(["getting-started.analyze_single_paper"])
    assert code == 0
    # sys.argv restored after run
    assert list(sys.argv) == before
    # But during execution, argv should have been set to the recipe path
    assert seen["argv"][0].endswith("cookbook/getting-started/analyze-single-paper.py")
