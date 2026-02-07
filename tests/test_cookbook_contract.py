"""Contract tests for cookbook recipe/docs consistency and runnability."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
import subprocess

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
def test_all_recipes_run_in_mock_mode() -> None:
    """Smoke test that each recipe runs successfully in mock mode."""
    commands = [
        "python -m cookbook getting-started/analyze-single-paper -- --input cookbook/data/demo/text-medium/input.txt --mock",
        "python -m cookbook getting-started/broadcast-process-files -- --input cookbook/data/demo/text-medium --limit 1 --mock",
        "python -m cookbook getting-started/extract-video-insights -- --input cookbook/data/demo/multimodal-basic/sample_video.mp4 --mock",
        "python -m cookbook optimization/cache-warming-and-ttl -- --input cookbook/data/demo/text-medium --limit 1 --ttl 300 --mock",
        "python -m cookbook optimization/context-caching-explicit -- --input cookbook/data/demo/text-medium --limit 1 --mock",
        "python -m cookbook optimization/large-scale-fan-out -- --input cookbook/data/demo/text-medium --limit 1 --concurrency 1 --mock",
        "python -m cookbook production/rate-limits-and-concurrency -- --input cookbook/data/demo/text-medium --limit 1 --concurrency 2 --mock",
        "python -m cookbook production/resume-on-failure -- --input cookbook/data/demo/text-medium --limit 1 --manifest /tmp/pollux_manifest.json --output-dir /tmp/pollux_items --mock",
        "python -m cookbook research-workflows/comparative-analysis -- cookbook/data/demo/text-medium/input.txt cookbook/data/demo/text-medium/compare.txt --mock",
        "python -m cookbook research-workflows/multi-video-synthesis -- --input-dir cookbook/data/demo/multimodal-basic --max-sources 1 --mock",
    ]
    for command in commands:
        result = subprocess.run(  # noqa: S603 - fixed local command list in test
            shlex.split(command),
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
