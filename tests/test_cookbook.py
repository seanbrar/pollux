"""Cookbook boundary tests.

Tests for the cookbook runner CLI—the boundary between user commands
and recipe execution.
"""

from __future__ import annotations

import runpy
from typing import TYPE_CHECKING, Any

import pytest

import cookbook.__main__ as runner
from cookbook.utils import data_packs

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


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

        called: dict[str, Any] = {}

        def fake_run_path(path: str, run_name: str) -> dict[str, Any]:
            called["path"] = path
            called["run_name"] = run_name
            return {}

        monkeypatch.setattr(runpy, "run_path", fake_run_path)

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
        assert called["run_name"] == "__main__"
        assert called["path"].endswith(
            "cookbook/getting-started/analyze-single-paper.py"
        )


def _write_shared_pack(root: Path) -> None:
    shared_root = root / "shared" / "v1"
    (shared_root / "text-medium").mkdir(parents=True)
    (shared_root / "multimodal-basic").mkdir(parents=True)
    (shared_root / "text-medium" / "input.txt").write_text("hello")
    (shared_root / "multimodal-basic" / "sample.pdf").write_text("pdf")
    (shared_root / "pack.toml").write_text(
        "\n".join(
            [
                'id = "shared"',
                'version = "1"',
                "",
                "[roles]",
                'text_dir = "text-medium"',
                'text_primary = "text-medium/input.txt"',
                'media_dir = "multimodal-basic"',
                'media_paper = "multimodal-basic/sample.pdf"',
            ]
        )
    )


def test_find_pack_root_prefers_configured_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Configured local data repo roots should resolve before installed data."""
    _write_shared_pack(tmp_path)
    monkeypatch.setenv(data_packs.ENV_DATA_SOURCE, str(tmp_path))

    resolved = data_packs.find_pack_root(data_packs.SHARED_PACK)

    assert resolved == tmp_path / "shared" / "v1"


def test_pack_role_path_reads_semantic_roles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Semantic role lookup should return the declared path inside the pack."""
    _write_shared_pack(tmp_path)
    monkeypatch.setenv(data_packs.ENV_DATA_SOURCE, str(tmp_path))

    resolved = data_packs.pack_role_path(data_packs.SHARED_PACK, "media_paper")

    assert resolved == tmp_path / "shared" / "v1" / "multimodal-basic" / "sample.pdf"


def test_pack_role_path_falls_back_to_installed_assets_when_source_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Role resolution should continue to installed data when source roots lack assets."""
    source_root = tmp_path / "source"
    install_root = tmp_path / "installed"
    _write_shared_pack(source_root)
    _write_shared_pack(install_root)
    (source_root / "shared" / "v1" / "text-medium" / "input.txt").unlink()
    monkeypatch.setattr(data_packs, "_REPO_ROOT", tmp_path / "missing-repo-root")
    monkeypatch.setenv(data_packs.ENV_DATA_SOURCE, str(source_root))
    monkeypatch.setenv(data_packs.ENV_DATA_DIR, str(install_root))

    resolved = data_packs.pack_role_path(data_packs.SHARED_PACK, "text_primary")

    assert resolved == install_root / "shared" / "v1" / "text-medium" / "input.txt"


def test_install_pack_copies_into_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pack installation should copy the requested pack into the install root."""
    source_root = tmp_path / "source"
    install_root = tmp_path / "installed"
    _write_shared_pack(source_root)
    monkeypatch.setenv(data_packs.ENV_DATA_SOURCE, str(source_root))
    monkeypatch.setenv(data_packs.ENV_DATA_DIR, str(install_root))

    installed_path, failures = data_packs.install_pack(
        data_packs.SHARED_PACK,
        dest_base=install_root,
        fetch_assets=False,
    )

    assert failures == []
    assert installed_path == install_root / "shared" / "v1"
    assert (installed_path / "text-medium" / "input.txt").read_text() == "hello"


def test_verify_checksum_supports_algorithm_prefixed_specs(tmp_path: Path) -> None:
    """Checksum verification should work for generic algorithm:digest specs."""
    target = tmp_path / "asset.bin"
    target.write_bytes(b"pollux cookbook asset")

    assert data_packs.verify_checksum(
        target,
        "sha256:df185629206418b0b81e158522449f8c195de692f41f345d9cf3591624026d73",
    )
    assert not data_packs.verify_checksum(
        target,
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )


def test_install_hint_matches_just_positional_argument_style() -> None:
    """Project install hints should use Just's positional recipe arguments."""
    assert data_packs.install_hint() == "just demo-data"
    assert data_packs.install_hint(project="spellbook-sidekick") == (
        "just demo-data spellbook-sidekick"
    )
