"""Contract tests for cookbook recipe/docs consistency and runnability."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

import pytest

import cookbook.__main__ as runner

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
CLI_DOC = ROOT / "docs" / "reference" / "cli.md"


def test_recipe_catalog_is_complete() -> None:
    """Every listed recipe appears in the CLI reference catalog table."""
    catalog_text = CLI_DOC.read_text()
    for spec in runner.list_recipes():
        # CLI docs use extensionless specs; strip .py for matching
        spec_name = Path(spec.display).with_suffix("").as_posix()
        assert spec_name in catalog_text, (
            f"recipe {spec_name!r} missing from {CLI_DOC.relative_to(ROOT)}"
        )


def test_no_stale_cookbook_doc_references() -> None:
    """User-facing entry points should not reference the removed cookbook docs layer."""
    stale_patterns = {
        ROOT / "README.md": [
            "https://polluxlib.dev/cookbook/",
            "https://polluxlib.dev/quickstart/",
            "https://polluxlib.dev/sources-and-patterns/",
            "https://polluxlib.dev/caching-and-efficiency/",
            "https://polluxlib.dev/troubleshooting/",
        ],
        ROOT / "cookbook" / "README.md": ["docs/cookbook/"],
    }

    for path, patterns in stale_patterns.items():
        if not path.exists():
            continue
        text = path.read_text()
        for pattern in patterns:
            assert pattern not in text, f"stale reference {pattern!r} found in {path}"


def _load_recipe_module(name: str, rel_path: str) -> Any:
    """Load a cookbook recipe module from disk for direct helper tests."""
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_lookup_name_handles_common_forms() -> None:
    """Common player spellings should move toward canonical PokeAPI ids.

    Unit test kept because Unicode edge cases (♀, apostrophes) are not
    exercised by the mock-mode smoke test.
    """
    recipe = _load_recipe_module(
        "pokedex_analyst", "cookbook/projects/pokedex-analyst.py"
    )
    assert recipe.normalize_lookup_name("Mr Mime") == "mr-mime"
    assert recipe.normalize_lookup_name("Farfetch'd") == "farfetchd"
    assert recipe.normalize_lookup_name("Nidoran♀") == "nidoran-f"


@pytest.mark.integration
def test_all_recipes_run_in_mock_mode(tmp_path: Path) -> None:
    """Smoke test that each recipe runs successfully in mock mode.

    CI does not include the cookbook demo-data packs. This test creates minimal
    local inputs so recipes can run without network access or pre-seeded files.
    """
    text_dir = tmp_path / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    input_txt = text_dir / "input.txt"
    compare_txt = text_dir / "compare.txt"
    input_txt.write_text("Pollux cookbook contract test input.\n")
    compare_txt.write_text("Second document for comparative analysis.\n")

    # Directory-based recipes expect a directory with supported extensions.
    (text_dir / "doc1.md").write_text("# Title\nSome content.\n")
    (text_dir / "doc2.txt").write_text("More content.\n")

    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    # These don't need to be valid media; the mock provider only requires that files exist.
    image = media_dir / "sample_image.jpg"
    video = media_dir / "sample_video.mp4"
    audio = media_dir / "sample_audio.mp3"
    image.write_bytes(b"fake-jpg")
    video.write_bytes(b"fake-mp4")
    audio.write_bytes(b"fake-mp3")

    manifest = tmp_path / "manifest.json"
    items_dir = tmp_path / "items"

    commands = [
        f"python -m cookbook getting-started/analyze-single-paper --input {input_txt} --mock",
        f"python -m cookbook getting-started/broadcast-process-files --input {text_dir} --limit 1 --mock",
        f"python -m cookbook getting-started/structured-output-extraction --input {input_txt} --mock",
        f"python -m cookbook getting-started/extract-media-insights --input {image} --mock",
        f"python -m cookbook getting-started/extract-media-insights --input {video} --mock",
        f"python -m cookbook getting-started/extract-media-insights --input {audio} --mock",
        f"python -m cookbook projects/paper-to-workshop-kit --input {input_txt} --mock",
        "python -m cookbook projects/pokedex-analyst pikachu gyarados ferrothorn --mock",
        f"python -m cookbook optimization/cache-warming-and-ttl --input {text_dir} --limit 1 --ttl 300 --mock",
        f"python -m cookbook optimization/large-scale-fan-out --input {text_dir} --limit 1 --concurrency 1 --mock",
        f"python -m cookbook optimization/run-vs-run-many --input {input_txt} --mock",
        f"python -m cookbook production/rate-limits-and-concurrency --input {text_dir} --limit 1 --concurrency 2 --mock",
        f"python -m cookbook production/resume-on-failure --input {text_dir} --limit 1 --manifest {manifest} --output-dir {items_dir} --mock",
        f"python -m cookbook research-workflows/comparative-analysis --input {input_txt} {compare_txt} --mock",
        f"python -m cookbook research-workflows/multi-video-synthesis --input {media_dir} --max-sources 1 --mock",
    ]
    for command in commands:
        parts = shlex.split(command)
        parts[0] = sys.executable
        result = subprocess.run(  # noqa: S603 - fixed local command list in test
            parts,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"command failed: {command}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
