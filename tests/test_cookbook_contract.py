"""Contract tests for cookbook recipe/docs consistency and runnability."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys

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
