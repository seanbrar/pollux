#!/usr/bin/env python3
"""Recipe: Turn a spellcaster sheet into a one-session spell packet.

Problem:
    Spellcasters accumulate enough options that the good turns blur together.
    You want a compact packet that helps you actually use the kit you already
    prepared.

When to use:
    - You have a character sheet image/PDF or a short spell list and want a
      session-ready quick-reference packet.
    - You want a project recipe that reads a character sheet, looks up spell
      rules from an API, and writes spell cards in parallel.

When not to use:
    - You want a full character builder or rules engine.
    - You need exhaustive spell coverage instead of a small play packet.

Run:
    python -m cookbook projects/spellbook-sidekick \\
      --sheet path/to/character-sheet.pdf \\
      --note "Dungeon crawl with tight spaces and lots of undead." \\
      --no-mock

Success check:
    - Output includes a normalized caster snapshot and 3-5 spell cards.
    - The packet surfaces concentration collisions and opener ideas.
"""

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from cookbook.utils.data_packs import (
    PackSpec,
    find_pack_root,
    install_hint,
    load_pack_manifest,
)
from cookbook.utils.presentation import (
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit, merged_usage
from pollux import Config, Options, Source, run, run_many
from pollux.result import ResultEnvelope

API_BASE = "https://www.dnd5eapi.co/api/2014"
MAX_SPELLS = 5
SPELLBOOK_PACK = PackSpec(
    namespace="projects", pack_id="spellbook-sidekick", version="1"
)

CLASS_ALIASES = {
    "artificer": "artificer",
    "bard": "bard",
    "cleric": "cleric",
    "druid": "druid",
    "paladin": "paladin",
    "ranger": "ranger",
    "sorcerer": "sorcerer",
    "sorc": "sorcerer",
    "warlock": "warlock",
    "wiz": "wizard",
    "wizard": "wizard",
}

LOOKUP_TOOL = {
    "name": "lookup_spell",
    "description": "Choose the closest canonical D&D spell name from the user's list.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Canonical spell name using the closest D&D 5e API spelling.",
            }
        },
        "required": ["name"],
    },
}


class SpellbookSnapshot(BaseModel):
    character_name: str = Field(description="Character name.")
    character_class: str = Field(description="Normalized spellcasting class.")
    level: int = Field(description="Character level from 1 to 20.")
    spell_names: list[str] = Field(
        description="3-5 table-relevant spells for this session."
    )
    playstyle_notes: list[str] = Field(
        description="Short notes about how this caster likely approaches the session."
    )


class SpellCard(BaseModel):
    spell_name: str = Field(description="Canonical spell name.")
    spell_level: int = Field(description="Spell level, with 0 for cantrips.")
    school: str = Field(description="Magic school.")
    best_moment: str = Field(description="When this spell shines in one sentence.")
    why_it_matters: str = Field(
        description="Why it matters for this character or session."
    )
    caution: str = Field(description="One practical caution or tradeoff.")


class SpellPacketSummary(BaseModel):
    headline: str = Field(description="Short title for the packet.")
    character_read: str = Field(
        description="2-3 sentence read on the caster and session."
    )
    opener_ideas: list[str] = Field(
        description="2-4 ways to start a fight or scene strong."
    )
    collision_warnings: list[str] = Field(
        description="2-4 collision or overload warnings, especially concentration conflicts."
    )
    table_notes: list[str] = Field(
        description="Short DM/player notes for using the packet."
    )


@dataclass(frozen=True, slots=True)
class SpellbookPackDefaults:
    """Resolved defaults from an installed spellbook starter pack."""

    pack_id: str
    character_slug: str
    scenario_slug: str
    snapshot: SpellbookSnapshot
    note: str
    session_brief: str


MOCK_SNAPSHOT = SpellbookSnapshot(
    character_name="Iri",
    character_class="wizard",
    level=5,
    spell_names=["Shield", "Misty Step", "Web", "Counterspell"],
    playstyle_notes=[
        "Likes controlling the room before damage starts.",
        "Prefers solving problems with positioning and prepared answers.",
    ],
)

MOCK_FACTS = {
    "shield": {
        "name": "Shield",
        "level": 1,
        "school": "Abjuration",
        "range": "Self",
        "casting_time": "1 reaction",
        "concentration": False,
        "ritual": False,
        "classes": ["sorcerer", "wizard"],
        "desc": [
            "An invisible barrier of magical force appears and protects you.",
        ],
    },
    "misty-step": {
        "name": "Misty Step",
        "level": 2,
        "school": "Conjuration",
        "range": "Self",
        "casting_time": "1 bonus action",
        "concentration": False,
        "ritual": False,
        "classes": ["sorcerer", "warlock", "wizard"],
        "desc": [
            "Briefly surrounded by silvery mist, you teleport up to 30 feet.",
        ],
    },
    "web": {
        "name": "Web",
        "level": 2,
        "school": "Conjuration",
        "range": "60 feet",
        "casting_time": "1 action",
        "concentration": True,
        "ritual": False,
        "classes": ["sorcerer", "wizard"],
        "desc": [
            "Conjures a mass of sticky webbing that can restrain creatures.",
        ],
    },
    "counterspell": {
        "name": "Counterspell",
        "level": 3,
        "school": "Abjuration",
        "range": "60 feet",
        "casting_time": "1 reaction",
        "concentration": False,
        "ritual": False,
        "classes": ["sorcerer", "warlock", "wizard"],
        "desc": [
            "Interrupt a creature in the process of casting a spell.",
        ],
    },
}


def _collapse_markdown(text: str) -> str:
    """Turn pack-authored markdown into a compact prompt-friendly paragraph."""
    pieces: list[str] = []
    for raw in text.splitlines():
        cleaned = re.sub(r"^\s*#+\s*", "", raw).strip()
        cleaned = re.sub(r"^\s*[-*]\s*", "", cleaned).strip()
        if cleaned:
            pieces.append(cleaned)
    return " ".join(pieces)


def should_try_default_pack(
    *,
    sheet: Path | None,
    pack_id: str | None,
    explicit_spells: list[str],
    character_name: str | None,
    character_class: str | None,
    level: int | None,
) -> bool:
    """Return whether the recipe should auto-upgrade to the starter pack."""
    return (
        pack_id is None
        and sheet is None
        and not explicit_spells
        and character_name is None
        and character_class is None
        and level is None
    )


def load_pack_defaults(
    *,
    pack_id: str | None,
    character_slug: str | None,
    scenario_slug: str | None,
    sheet: Path | None,
    explicit_spells: list[str],
    character_name: str | None,
    character_class: str | None,
    level: int | None,
) -> SpellbookPackDefaults | None:
    """Load spellbook starter-pack defaults when requested or available."""
    requested_pack = pack_id
    explicit_request = any(
        value is not None for value in (pack_id, character_slug, scenario_slug)
    )
    if should_try_default_pack(
        sheet=sheet,
        pack_id=pack_id,
        explicit_spells=explicit_spells,
        character_name=character_name,
        character_class=character_class,
        level=level,
    ):
        requested_pack = SPELLBOOK_PACK.pack_id
    if requested_pack is None:
        return None

    spec = PackSpec(namespace="projects", pack_id=requested_pack, version="1")
    pack_root = find_pack_root(spec)
    if pack_root is None:
        if not explicit_request:
            return None
        raise SystemExit(
            f"Pack {requested_pack!r} is not installed. "
            f"Run `{install_hint(project=requested_pack)}` first."
        )

    manifest = load_pack_manifest(spec) or {}
    recipe_spec = manifest.get("recipe_spec")
    if recipe_spec not in {None, "projects/spellbook-sidekick"}:
        raise SystemExit(
            f"Pack {requested_pack!r} targets {recipe_spec!r}, not spellbook-sidekick."
        )

    default_character = manifest.get("default_character")
    default_scenario = manifest.get("default_scenario")
    chosen_character = character_slug or (
        str(default_character) if isinstance(default_character, str) else None
    )
    chosen_scenario = scenario_slug or (
        str(default_scenario) if isinstance(default_scenario, str) else None
    )
    if not chosen_character or not chosen_scenario:
        raise SystemExit(
            f"Pack {requested_pack!r} is missing default character or scenario metadata."
        )

    character_path = pack_root / "characters" / chosen_character / "character.json"
    scenario_path = pack_root / "scenarios" / f"{chosen_scenario}.md"
    if not character_path.exists():
        raise SystemExit(
            f"Character {chosen_character!r} not found in pack {requested_pack!r}."
        )
    if not scenario_path.exists():
        raise SystemExit(
            f"Scenario {chosen_scenario!r} not found in pack {requested_pack!r}."
        )

    payload = json.loads(character_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Character profile at {character_path} is not a JSON object.")

    scenario_notes = payload.get("scenario_notes")
    note = ""
    if isinstance(scenario_notes, dict):
        raw_note = scenario_notes.get(chosen_scenario)
        if isinstance(raw_note, str):
            note = raw_note.strip()

    playstyle_notes = payload.get("playstyle_notes")
    spells = payload.get("signature_spells")
    snapshot = SpellbookSnapshot(
        character_name=str(payload.get("name", chosen_character)).strip()
        or chosen_character,
        character_class=normalize_class_name(str(payload.get("class", ""))),
        level=int(payload.get("level", 1) or 1),
        spell_names=dedupe_spell_names(
            [spell for spell in spells if isinstance(spell, str)]
            if isinstance(spells, list)
            else []
        )[:MAX_SPELLS],
        playstyle_notes=[
            note
            for note in (playstyle_notes if isinstance(playstyle_notes, list) else [])
            if isinstance(note, str) and note.strip()
        ][:3]
        or ["Loaded from a cookbook starter pack."],
    )
    return SpellbookPackDefaults(
        pack_id=requested_pack,
        character_slug=chosen_character,
        scenario_slug=chosen_scenario,
        snapshot=snapshot,
        note=note,
        session_brief=_collapse_markdown(scenario_path.read_text(encoding="utf-8")),
    )


def normalize_class_name(raw: str) -> str:
    """Normalize class labels toward a stable spellcaster vocabulary."""
    cleaned = re.sub(r"[^a-z]", "", raw.strip().lower())
    normalized = CLASS_ALIASES.get(cleaned)
    if normalized is None:
        known = ", ".join(sorted(CLASS_ALIASES))
        raise ValueError(f"Unknown class {raw!r}. Known forms include: {known}.")
    return normalized


def normalize_spell_name(raw: str) -> str:
    """Normalize free-form spell labels toward API-compatible keys."""
    cleaned = raw.strip().lower()
    cleaned = cleaned.replace("'", "")
    cleaned = cleaned.replace("/", "-")
    cleaned = re.sub(r"[^a-z0-9\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    return re.sub(r"-+", "-", cleaned).strip("-")


def dedupe_spell_names(spells: list[str]) -> list[str]:
    """Return stable unique spell names, preserving original order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in spells:
        cleaned = raw.strip()
        if not cleaned:
            continue
        key = normalize_spell_name(cleaned)
        if key and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def parse_tool_arguments(raw: object) -> dict[str, Any]:
    """Parse provider-normalized tool-call arguments."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def plan_lookup_names(
    spell_names: list[str], tool_calls: list[dict[str, Any]]
) -> list[str]:
    """Map tool calls back onto the extracted spell order."""
    planned: list[str] = []
    for idx, raw_name in enumerate(spell_names):
        call = tool_calls[idx] if idx < len(tool_calls) else {}
        args = parse_tool_arguments(call.get("arguments"))
        requested = args.get("name")
        planned.append(str(requested).strip() if requested else raw_name)
    return planned


def spell_card_prompt(spell_name: str) -> str:
    """Return the fan-out prompt for one spell card."""
    return (
        f"Build a compact quick-reference card for {spell_name}. "
        "Focus on one good moment to deploy it, why it matters for this session, "
        "and one caution that keeps the player honest."
    )


def build_extraction_prompt(note: str) -> str:
    """Return the multimodal extraction prompt for a character sheet."""
    note_text = note.strip()
    extra = f" Session note: {note_text}." if note_text else ""
    return (
        "Extract a compact spellcaster snapshot from this character sheet. "
        "Return the character name, class, level, 3-5 spells that look most table-relevant, "
        "and short playstyle notes." + extra
    )


def build_lookup_prompt(snapshot: SpellbookSnapshot) -> str:
    """Return the bounded tool-planning prompt."""
    joined = ", ".join(snapshot.spell_names)
    return (
        f"Character: {snapshot.character_name}, {snapshot.character_class} level {snapshot.level}. "
        f"Spells: {joined}. "
        "Call lookup_spell exactly once for each spell, in order. "
        "Use the closest canonical D&D 5e API spell name. Do not explain anything."
    )


def build_summary_prompt(note: str) -> str:
    """Return the final synthesis prompt."""
    note_text = note.strip()
    extra = f" Session note: {note_text}." if note_text else ""
    return (
        "Write a compact one-session spell packet for this caster." + extra + " "
        "Be practical, not theatrical. Surface concentration conflicts, overloaded reactions or bonus actions, "
        "and 2-4 concrete opener ideas."
    )


def request_json(url: str) -> dict[str, Any]:
    """Fetch one JSON document from the D&D API."""
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "pollux-cookbook/spellbook-sidekick",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"Expected JSON object from {url}")
            return cast("dict[str, Any]", payload)
    except HTTPError as exc:
        raise RuntimeError(f"D&D API HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"D&D API request failed for {url}: {exc.reason}") from exc


def fetch_spell_catalog() -> dict[str, tuple[str, str]]:
    """Fetch canonical spell names and indexes keyed by normalized name."""
    payload = request_json(f"{API_BASE}/spells")
    results = payload.get("results", [])
    catalog: dict[str, tuple[str, str]] = {}
    if not isinstance(results, list):
        return catalog
    for item in results:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        index = item.get("index")
        if isinstance(name, str) and isinstance(index, str):
            catalog[normalize_spell_name(name)] = (name, index)
    return catalog


def resolve_spell_lookup(
    raw_name: str, catalog: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    """Resolve a raw spell label against the live catalog."""
    key = normalize_spell_name(raw_name)
    resolved = catalog.get(key)
    if resolved is None:
        raise RuntimeError(
            f"Spell {raw_name!r} not found in the D&D API catalog. Try a more canonical spelling."
        )
    return resolved


def normalize_spell_detail(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce a full spell payload into the facts this recipe needs."""
    desc = payload.get("desc")
    desc_lines = (
        [line for line in desc if isinstance(line, str)]
        if isinstance(desc, list)
        else []
    )
    classes = payload.get("classes", [])
    return {
        "name": str(payload.get("name", "Unknown spell")),
        "level": int(payload.get("level", 0) or 0),
        "school": str(payload.get("school", {}).get("name", "")),
        "range": str(payload.get("range", "")),
        "casting_time": str(payload.get("casting_time", "")),
        "concentration": bool(payload.get("concentration", False)),
        "ritual": bool(payload.get("ritual", False)),
        "classes": [
            str(item.get("name", "")).lower()
            for item in classes
            if isinstance(item, dict) and item.get("name")
        ],
        "desc": desc_lines[:2],
    }


def fetch_spell_detail(index: str) -> dict[str, Any]:
    """Fetch one normalized spell record."""
    payload = request_json(f"{API_BASE}/spells/{index}")
    return normalize_spell_detail(payload)


def mock_spell_detail(raw_name: str) -> dict[str, Any]:
    """Return canned spell facts for mock mode."""
    key = normalize_spell_name(raw_name)
    detail = MOCK_FACTS.get(key)
    if detail is not None:
        return detail
    return {
        "name": raw_name.strip().title() or "Unknown Spell",
        "level": 1,
        "school": "Abjuration",
        "range": "Self",
        "casting_time": "1 action",
        "concentration": False,
        "ritual": False,
        "classes": ["wizard"],
        "desc": ["A credible mock spell used to validate the packet flow."],
    }


def build_manual_snapshot(
    *,
    character_name: str | None,
    character_class: str | None,
    level: int | None,
    spells: list[str],
    note: str,
) -> SpellbookSnapshot:
    """Build a snapshot from explicit CLI inputs."""
    if character_class is None or level is None or not spells:
        raise SystemExit(
            "Provide --sheet, or pass --class, --level, and at least one --spell."
        )
    normalized_spells = dedupe_spell_names(spells)[:MAX_SPELLS]
    return SpellbookSnapshot(
        character_name=(character_name or "Unnamed caster").strip() or "Unnamed caster",
        character_class=normalize_class_name(character_class),
        level=int(level),
        spell_names=normalized_spells,
        playstyle_notes=[
            "Built from explicit spell inputs instead of sheet extraction.",
            note.strip() or "No extra session note provided.",
        ],
    )


def merge_snapshot_spells(
    snapshot: SpellbookSnapshot, extra_spells: list[str]
) -> SpellbookSnapshot:
    """Merge extracted and explicit spells into a capped stable list."""
    merged = dedupe_spell_names(snapshot.spell_names + extra_spells)[:MAX_SPELLS]
    return SpellbookSnapshot(
        character_name=snapshot.character_name,
        character_class=snapshot.character_class,
        level=snapshot.level,
        spell_names=merged or snapshot.spell_names[:MAX_SPELLS],
        playstyle_notes=snapshot.playstyle_notes,
    )


def apply_snapshot_overrides(
    snapshot: SpellbookSnapshot,
    *,
    character_name: str | None,
    character_class: str | None,
    level: int | None,
) -> SpellbookSnapshot:
    """Apply explicit CLI overrides on top of a resolved snapshot."""
    return SpellbookSnapshot(
        character_name=(
            character_name.strip()
            if character_name is not None
            else snapshot.character_name
        )
        or snapshot.character_name,
        character_class=(
            normalize_class_name(character_class)
            if character_class is not None
            else snapshot.character_class
        ),
        level=int(level) if level is not None else snapshot.level,
        spell_names=snapshot.spell_names,
        playstyle_notes=snapshot.playstyle_notes,
    )


def fallback_card(snapshot: SpellbookSnapshot, fact: dict[str, Any]) -> SpellCard:
    """Build a stable spell card when structured output fails."""
    caution = f"Range: {fact['range']} | cast time: {fact['casting_time']}."
    if fact.get("concentration"):
        caution += " Watch concentration."
    return SpellCard(
        spell_name=fact["name"],
        spell_level=int(fact["level"]),
        school=str(fact["school"]),
        best_moment=f"Use {fact['name']} when the current problem matches its lane.",
        why_it_matters=(
            f"{fact['name']} suits {snapshot.character_name}'s {snapshot.character_class} toolkit for this session."
        ),
        caution=caution,
    )


def fallback_summary(
    snapshot: SpellbookSnapshot,
    *,
    note: str,
    cards: list[SpellCard],
    spell_facts: list[dict[str, Any]],
) -> SpellPacketSummary:
    """Build a stable packet summary when structured output fails."""
    concentration = [fact["name"] for fact in spell_facts if fact.get("concentration")]
    reactions = [
        fact["name"]
        for fact in spell_facts
        if "reaction" in str(fact.get("casting_time", "")).lower()
    ]
    return SpellPacketSummary(
        headline=f"{snapshot.character_name}'s one-session spell packet",
        character_read=(
            f"{snapshot.character_name} is a level {snapshot.level} "
            f"{snapshot.character_class} entering a session where {note or 'prepared choices matter'}."
        ),
        opener_ideas=[
            f"Start with {cards[0].spell_name} if the table needs immediate control or safety.",
            "Save one fast response for when the encounter turns weird.",
        ],
        collision_warnings=[
            "Concentration stack: " + ", ".join(concentration)
            if concentration
            else "No concentration-heavy collisions surfaced in the chosen packet.",
            "Reaction load: " + ", ".join(reactions)
            if reactions
            else "Reaction pressure looks manageable from this spell set.",
        ],
        table_notes=[
            "Do not try to cast every cool spell; pick a lane for the first two rounds.",
            "If the room layout changes, re-evaluate your range and concentration plan.",
        ],
    )


def print_snapshot(snapshot: SpellbookSnapshot, *, note: str) -> None:
    """Print the normalized caster snapshot."""
    print_section("Caster snapshot")
    print_kv_rows(
        [
            ("Character", snapshot.character_name),
            ("Class", snapshot.character_class.title()),
            ("Level", snapshot.level),
            ("Spell count", len(snapshot.spell_names)),
            ("Session note", note or "none"),
        ]
    )
    print_section("Selected spells")
    for spell_name in snapshot.spell_names:
        print(f"- {spell_name}")


def print_cards(cards: list[SpellCard]) -> None:
    """Print the quick-reference spell cards."""
    print_section("Spell cards")
    for card in cards:
        print(f"- {card.spell_name} (level {card.spell_level}, {card.school})")
        print(f"  Best moment: {card.best_moment}")
        print(f"  Why it matters: {card.why_it_matters}")
        print(f"  Caution: {card.caution}")


def print_summary(summary: SpellPacketSummary) -> None:
    """Print the packet summary."""
    print_section("Spell packet")
    print(f"  {summary.headline}")
    print(f"  {summary.character_read}")

    print_section("Opener ideas")
    for item in summary.opener_ideas:
        print(f"- {item}")

    print_section("Collision warnings")
    for item in summary.collision_warnings:
        print(f"- {item}")

    print_section("Table notes")
    for item in summary.table_notes:
        print(f"- {item}")


async def extract_snapshot(
    *,
    sheet: Path | None,
    note: str,
    explicit_spells: list[str],
    character_name: str | None,
    character_class: str | None,
    level: int | None,
    pack_defaults: SpellbookPackDefaults | None,
    config: Config,
) -> tuple[SpellbookSnapshot, ResultEnvelope]:
    """Extract or build the initial spellbook snapshot."""
    if sheet is None:
        if config.use_mock:
            base_snapshot = (
                pack_defaults.snapshot if pack_defaults is not None else MOCK_SNAPSHOT
            )
            base_snapshot = apply_snapshot_overrides(
                base_snapshot,
                character_name=character_name,
                character_class=character_class,
                level=level,
            )
            base_text = (
                pack_defaults.session_brief
                if pack_defaults is not None
                else (
                    "Mock spellcaster snapshot: Iri the wizard keeps Shield, "
                    "Misty Step, Web, and Counterspell ready."
                )
            )
            envelope = await run(
                "Give one short sentence about a prepared wizard.",
                source=Source.from_text(
                    base_text,
                    identifier="mock-spellcaster",
                ),
                config=config,
            )
            snapshot = merge_snapshot_spells(base_snapshot, explicit_spells)
            return snapshot, envelope
        if pack_defaults is not None:
            snapshot = merge_snapshot_spells(
                apply_snapshot_overrides(
                    pack_defaults.snapshot,
                    character_name=character_name,
                    character_class=character_class,
                    level=level,
                ),
                explicit_spells,
            )
            envelope = await run(
                "Give one sentence about this spellcaster.",
                source=Source.from_json(
                    {
                        "caster": snapshot.model_dump(),
                        "session_brief": pack_defaults.session_brief,
                    },
                    identifier="pack-spellcaster",
                ),
                config=config,
            )
            return snapshot, envelope
        snapshot = build_manual_snapshot(
            character_name=character_name,
            character_class=character_class,
            level=level,
            spells=explicit_spells,
            note=note,
        )
        envelope = await run(
            "Give one sentence about this spellcaster.",
            source=Source.from_json(snapshot, identifier="manual-spellcaster"),
            config=config,
        )
        return snapshot, envelope

    sources: list[Source] = [Source.from_file(sheet)]
    if pack_defaults is not None and pack_defaults.session_brief:
        sources.append(
            Source.from_text(
                pack_defaults.session_brief,
                identifier="scenario-brief",
            )
        )
    if note.strip():
        sources.append(
            Source.from_text(f"Session note: {note.strip()}", identifier="session-note")
        )
    extraction_env = await run_many(
        [build_extraction_prompt(note)],
        sources=sources,
        config=config,
        options=Options(response_schema=SpellbookSnapshot)
        if not config.use_mock
        else None,
    )
    structured = extraction_env.get("structured", [])
    first = structured[0] if isinstance(structured, list) and structured else None
    if isinstance(first, SpellbookSnapshot):
        snapshot = merge_snapshot_spells(first, explicit_spells)
        return snapshot, extraction_env

    if config.use_mock:
        return merge_snapshot_spells(MOCK_SNAPSHOT, explicit_spells), extraction_env

    snapshot = build_manual_snapshot(
        character_name=character_name,
        character_class=character_class,
        level=level,
        spells=explicit_spells,
        note=note,
    )
    return snapshot, extraction_env


async def lookup_spell_facts(
    snapshot: SpellbookSnapshot,
    *,
    config: Config,
) -> tuple[list[dict[str, Any]], ResultEnvelope]:
    """Normalize spell names with tool calls, then fetch spell facts."""
    lookup_env = await run(
        build_lookup_prompt(snapshot),
        config=config,
        options=Options(tools=[LOOKUP_TOOL], tool_choice={"name": "lookup_spell"}),
    )
    raw_tool_calls = lookup_env.get("tool_calls")
    tool_calls = (
        raw_tool_calls[0] if isinstance(raw_tool_calls, list) and raw_tool_calls else []
    )
    lookup_names = plan_lookup_names(snapshot.spell_names, tool_calls)

    if config.use_mock:
        facts = [mock_spell_detail(name) for name in lookup_names]
    else:
        catalog = await asyncio.to_thread(fetch_spell_catalog)
        resolved = [resolve_spell_lookup(name, catalog) for name in lookup_names]
        facts = await asyncio.gather(
            *[asyncio.to_thread(fetch_spell_detail, index) for _, index in resolved]
        )

    lookup_env.setdefault("metrics", {})
    lookup_env["metrics"]["tool_calls_seen"] = len(tool_calls)
    return facts, lookup_env


async def build_cards(
    snapshot: SpellbookSnapshot,
    *,
    spell_facts: list[dict[str, Any]],
    session_brief: str,
    config: Config,
) -> tuple[list[SpellCard], ResultEnvelope]:
    """Fan out one prompt per spell to build quick-reference cards."""
    card_env = await run_many(
        [spell_card_prompt(fact["name"]) for fact in spell_facts],
        sources=[
            Source.from_json(
                {
                    "caster": snapshot.model_dump(),
                    "session_brief": session_brief,
                    "spells": spell_facts,
                },
                identifier="spell-facts",
            )
        ],
        config=config,
        options=Options(response_schema=SpellCard) if not config.use_mock else None,
    )
    if config.use_mock:
        return [fallback_card(snapshot, fact) for fact in spell_facts], card_env
    structured = card_env.get("structured", [])
    cards: list[SpellCard] = []
    for idx, fact in enumerate(spell_facts):
        candidate = (
            structured[idx]
            if isinstance(structured, list) and idx < len(structured)
            else None
        )
        if isinstance(candidate, SpellCard):
            cards.append(candidate)
        else:
            cards.append(fallback_card(snapshot, fact))
    return cards, card_env


async def build_summary(
    snapshot: SpellbookSnapshot,
    *,
    note: str,
    spell_facts: list[dict[str, Any]],
    cards: list[SpellCard],
    session_brief: str,
    config: Config,
) -> tuple[SpellPacketSummary, ResultEnvelope]:
    """Build the final packet summary from normalized spell facts and cards."""
    summary_env = await run(
        build_summary_prompt(note),
        source=Source.from_json(
            {
                "caster": snapshot.model_dump(),
                "session_note": note,
                "session_brief": session_brief,
                "spells": spell_facts,
                "cards": [card.model_dump() for card in cards],
            },
            identifier="spell-packet-input",
        ),
        config=config,
        options=Options(response_schema=SpellPacketSummary)
        if not config.use_mock
        else None,
    )
    if config.use_mock:
        return fallback_summary(
            snapshot, note=note, cards=cards, spell_facts=spell_facts
        ), summary_env
    structured = summary_env.get("structured", [])
    first = structured[0] if isinstance(structured, list) and structured else None
    summary = (
        first
        if isinstance(first, SpellPacketSummary)
        else fallback_summary(snapshot, note=note, cards=cards, spell_facts=spell_facts)
    )
    return summary, summary_env


async def main_async(
    *,
    sheet: Path | None,
    note: str,
    explicit_spells: list[str],
    character_name: str | None,
    character_class: str | None,
    level: int | None,
    pack_defaults: SpellbookPackDefaults | None,
    config: Config,
) -> None:
    snapshot, extraction_env = await extract_snapshot(
        sheet=sheet,
        note=note,
        explicit_spells=explicit_spells,
        character_name=character_name,
        character_class=character_class,
        level=level,
        pack_defaults=pack_defaults,
        config=config,
    )
    spell_facts, lookup_env = await lookup_spell_facts(snapshot, config=config)
    cards, card_env = await build_cards(
        snapshot,
        spell_facts=spell_facts,
        session_brief=pack_defaults.session_brief
        if pack_defaults is not None
        else note,
        config=config,
    )
    summary, summary_env = await build_summary(
        snapshot,
        note=note,
        spell_facts=spell_facts,
        cards=cards,
        session_brief=pack_defaults.session_brief
        if pack_defaults is not None
        else note,
        config=config,
    )

    envelope = merged_usage(extraction_env, lookup_env, card_env, summary_env)
    envelope.setdefault("metrics", {})
    envelope["metrics"]["tool_calls_seen"] = lookup_env.get("metrics", {}).get(
        "tool_calls_seen", 0
    )

    print_snapshot(snapshot, note=note)
    print_section("Packet snapshot")
    print_kv_rows(
        [
            ("Status", summary_env.get("status", "ok")),
            ("Sheet provided", bool(sheet)),
            (
                "Starter pack",
                (
                    f"{pack_defaults.pack_id}:{pack_defaults.character_slug}/{pack_defaults.scenario_slug}"
                    if pack_defaults is not None
                    else "none"
                ),
            ),
            ("Cards", len(cards)),
            ("Tool lookups", envelope.get("metrics", {}).get("tool_calls_seen", 0)),
        ]
    )
    print_cards(cards)
    print_summary(summary)
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: swap the session note and watch which spells stay in the packet.",
            "Next: fork the card prompt toward your own table's level of tactical detail.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn a spellcaster sheet or short spell list into a one-session spell packet.",
    )
    parser.add_argument(
        "--pack",
        default=None,
        help="Optional installed cookbook starter pack id (for example: spellbook-sidekick).",
    )
    parser.add_argument(
        "--character",
        default=None,
        help="Character slug inside the selected starter pack.",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario slug inside the selected starter pack.",
    )
    parser.add_argument(
        "--sheet",
        type=Path,
        default=None,
        help="Optional character sheet image or PDF. Strongly recommended for live runs.",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional session note, threat hint, or dungeon context.",
    )
    parser.add_argument(
        "--spell",
        action="append",
        default=[],
        help="Optional explicit spell to merge into the packet. Repeat for multiple spells.",
    )
    parser.add_argument(
        "--character-name",
        default=None,
        help="Optional name used when building from explicit spells without a sheet.",
    )
    parser.add_argument(
        "--class",
        dest="character_class",
        default=None,
        help="Spellcasting class used when building from explicit spells without a sheet.",
    )
    parser.add_argument(
        "--level",
        type=int,
        default=None,
        help="Character level used when building from explicit spells without a sheet.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    sheet: Path | None = args.sheet
    if sheet is not None and not sheet.exists():
        raise SystemExit(f"File not found: {sheet}")

    pack_defaults = load_pack_defaults(
        pack_id=args.pack,
        character_slug=args.character,
        scenario_slug=args.scenario,
        sheet=sheet,
        explicit_spells=list(args.spell),
        character_name=args.character_name,
        character_class=args.character_class,
        level=args.level,
    )
    base_spells = (
        pack_defaults.snapshot.spell_names
        if pack_defaults is not None and sheet is None
        else []
    )
    explicit_spells = dedupe_spell_names(base_spells + list(args.spell))[:MAX_SPELLS]
    note = args.note.strip() or (
        pack_defaults.note if pack_defaults is not None else ""
    )
    config = build_config_or_exit(args)
    print_header("Spellbook Sidekick", config=config)
    asyncio.run(
        main_async(
            sheet=sheet,
            note=note,
            explicit_spells=explicit_spells,
            character_name=args.character_name,
            character_class=args.character_class,
            level=args.level,
            pack_defaults=pack_defaults,
            config=config,
        )
    )


if __name__ == "__main__":
    main()
