"""Contract tests for cookbook recipe/docs consistency and runnability."""

from __future__ import annotations

import importlib.util
import os
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


def test_parse_pantry_note_dedupes_and_normalizes() -> None:
    """Pantry notes should become a small stable ingredient list."""
    recipe = _load_recipe_module("fridge_raid", "cookbook/projects/fridge-raid.py")
    assert recipe.parse_pantry_note(" Eggs, rice\nScallions, eggs ") == [
        "eggs",
        "rice",
        "scallions",
    ]


def test_parse_party_member_normalizes_class_and_level() -> None:
    """Party member CLI input should normalize class aliases and numeric levels."""
    recipe = _load_recipe_module(
        "treasure_tailor", "cookbook/projects/treasure-tailor.py"
    )
    member = recipe.parse_party_member("Nyx:wiz:5")
    assert member.name == "Nyx"
    assert member.character_class == "wizard"
    assert member.level == 5


def test_dedupe_spell_names_preserves_order() -> None:
    """Spell helpers should keep first-seen spell order while removing duplicates."""
    recipe = _load_recipe_module(
        "spellbook_sidekick", "cookbook/projects/spellbook-sidekick.py"
    )
    assert recipe.dedupe_spell_names(["Shield", " web ", "Shield", "Counterspell"]) == [
        "Shield",
        "web",
        "Counterspell",
    ]


def test_load_spellbook_pack_defaults_reads_profile_and_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spellbook starter packs should hydrate snapshot defaults from pack files."""
    pack_root = tmp_path / "projects" / "spellbook-sidekick" / "v1"
    (pack_root / "characters" / "iri-vale").mkdir(parents=True)
    (pack_root / "scenarios").mkdir(parents=True)
    (pack_root / "pack.toml").write_text(
        "\n".join(
            [
                'id = "spellbook-sidekick"',
                'version = "1"',
                'recipe_spec = "projects/spellbook-sidekick"',
                'default_character = "iri-vale"',
                'default_scenario = "tactical-corridor-crawl"',
            ]
        )
    )
    (pack_root / "characters" / "iri-vale" / "character.json").write_text(
        """{
  "name": "Iri Vale",
  "class": "wizard",
  "level": 5,
  "signature_spells": ["Shield", "Web", "Counterspell"],
  "playstyle_notes": ["Controls rooms before damage starts."],
  "scenario_notes": {
    "tactical-corridor-crawl": "Preserve one reaction for the first room."
  }
}
"""
    )
    (pack_root / "scenarios" / "tactical-corridor-crawl.md").write_text(
        "# Tactical Corridor Crawl\n\nTight rooms reward careful first-round play.\n"
    )
    monkeypatch.setenv("POLLUX_COOKBOOK_DATA_SOURCE", str(tmp_path))

    recipe = _load_recipe_module(
        "spellbook_sidekick", "cookbook/projects/spellbook-sidekick.py"
    )
    defaults = recipe.load_pack_defaults(
        pack_id="spellbook-sidekick",
        character_slug=None,
        scenario_slug=None,
        sheet=None,
        explicit_spells=[],
        character_name=None,
        character_class=None,
        level=None,
    )

    assert defaults is not None
    assert defaults.character_slug == "iri-vale"
    assert defaults.scenario_slug == "tactical-corridor-crawl"
    assert defaults.snapshot.character_name == "Iri Vale"
    assert defaults.snapshot.spell_names == ["Shield", "Web", "Counterspell"]
    assert "Tight rooms reward careful first-round play." in defaults.session_brief


def test_spellbook_pack_cli_overrides_take_precedence(tmp_path: Path) -> None:
    """Explicit CLI fields should override starter-pack identity defaults."""
    pack_root = tmp_path / "projects" / "spellbook-sidekick" / "v1"
    (pack_root / "characters" / "iri-vale").mkdir(parents=True)
    (pack_root / "scenarios").mkdir(parents=True)
    (pack_root / "pack.toml").write_text(
        "\n".join(
            [
                'id = "spellbook-sidekick"',
                'version = "1"',
                'recipe_spec = "projects/spellbook-sidekick"',
                'default_character = "iri-vale"',
                'default_scenario = "tactical-corridor-crawl"',
            ]
        )
    )
    (pack_root / "characters" / "iri-vale" / "character.json").write_text(
        """{
  "name": "Iri Vale",
  "class": "wizard",
  "level": 5,
  "signature_spells": ["Shield", "Web"]
}
"""
    )
    (pack_root / "scenarios" / "tactical-corridor-crawl.md").write_text(
        "# Tactical Corridor Crawl\n\nTight rooms reward careful first-round play.\n"
    )

    result = subprocess.run(  # noqa: S603 - fixed local command list in test
        [
            sys.executable,
            "-m",
            "cookbook",
            "projects/spellbook-sidekick",
            "--pack",
            "spellbook-sidekick",
            "--character-name",
            "Override Name",
            "--class",
            "sorcerer",
            "--level",
            "9",
            "--mock",
        ],
        cwd=ROOT,
        env={**os.environ, "POLLUX_COOKBOOK_DATA_SOURCE": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "- Character: Override Name" in result.stdout
    assert "- Class: Sorcerer" in result.stdout
    assert "- Level: 9" in result.stdout


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
        f"python -m cookbook projects/fridge-raid {image} --note 'eggs, rice' --mock",
        f"python -m cookbook projects/paper-to-workshop-kit --input {input_txt} --mock",
        "python -m cookbook projects/pokedex-analyst pikachu gyarados ferrothorn --mock",
        (
            "python -m cookbook projects/spellbook-sidekick "
            "--spell Shield "
            "--spell Web "
            "--spell Counterspell "
            "--class wizard "
            "--level 5 "
            "--mock"
        ),
        (
            "python -m cookbook projects/treasure-tailor "
            "--party-member 'Nyx:rogue:5' "
            "--party-member 'Brakka:fighter:5' "
            "--party-member 'Iri:wiz:5' "
            "--summary 'The party cleared a flooded observatory.' "
            "--mock"
        ),
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
