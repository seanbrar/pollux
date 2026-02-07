"""Contract tests for cookbook recipe/docs consistency and runnability."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

import cookbook.__main__ as runner

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = ROOT / "docs" / "cookbook"

REQUIRED_DOC_SECTIONS = [
    "## At a glance",
    "## Before you run",
    "## Command",
    "## What to look for",
    "## Tuning levers",
    "## Failure modes",
    "## Extend this recipe",
]


def doc_path_for_recipe(spec: runner.RecipeSpec) -> Path:
    """Map cookbook recipe path to its docs page path."""
    return DOCS_ROOT / Path(spec.display).with_suffix(".md")


def extract_bash_blocks(text: str) -> list[str]:
    """Return fenced bash code blocks from docs content."""
    return re.findall(r"```bash\\n(.*?)```", text, flags=re.DOTALL)


def commands_from_block(block: str) -> list[str]:
    """Split one bash block into individual command strings."""
    commands: list[str] = []
    lines: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line.rstrip("\\").strip())
    if lines:
        commands.append(" ".join(lines))
    return commands


def test_recipe_docs_mapping_is_complete() -> None:
    """Every listed recipe has a docs page with required sections."""
    for spec in runner.list_recipes():
        doc_path = doc_path_for_recipe(spec)
        assert doc_path.exists(), f"missing docs page: {doc_path}"
        content = doc_path.read_text()
        for heading in REQUIRED_DOC_SECTIONS:
            assert heading in content, f"{doc_path} missing section: {heading}"


def test_doc_commands_resolve_to_known_recipes() -> None:
    """Every python -m cookbook command in recipe docs resolves cleanly."""
    for spec in runner.list_recipes():
        content = doc_path_for_recipe(spec).read_text()
        for block in extract_bash_blocks(content):
            for command in commands_from_block(block):
                if "python -m cookbook" not in command:
                    continue
                parts = shlex.split(command)
                idx = parts.index("cookbook")
                recipe_spec = parts[idx + 1]
                if recipe_spec.startswith("--"):
                    continue
                resolved = runner.resolve_spec(recipe_spec)
                assert resolved.path.exists(), f"unresolved command spec: {recipe_spec}"


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
            f"command failed: {command}\\n"
            f"stdout:\\n{result.stdout}\\n"
            f"stderr:\\n{result.stderr}"
        )
