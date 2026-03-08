#!/usr/bin/env python3
"""Recipe: Turn party notes into a tailored DnD treasure packet.

Problem:
    Random loot tables are fast, but they rarely feel like they were meant for
    this party or this session. You want a reward packet with both table value
    and a little ceremony.

When to use:
    - You have a short party roster and want tonight's rewards to feel specific.
    - You want a project recipe that picks rewards from the SRD, scores them
      against a real party, and writes a DM-ready packet.

When not to use:
    - You want a full campaign inventory manager or procedural loot generator.
    - You need strict rules adjudication beyond quick caveats and reminders.

Run:
    python -m cookbook projects/treasure-tailor \\
      --party-member "Nyx:rogue:5" \\
      --party-member "Brakka:fighter:5" \\
      --party-member "Iri:wizard:5" \\
      --summary "The party cleared a flooded observatory." \\
      --no-mock

Success check:
    - Output includes three distinct rewards with canonical rules grounding.
    - Each reward has a best-fit recipient, reveal text, and caveats.
"""

import argparse
import asyncio
from dataclasses import dataclass
import json
import re
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

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
PARTY_MIN_SIZE = 2
PARTY_MAX_SIZE = 6
MAX_SLOT_CANDIDATES = 6
REWARD_TYPE_LABELS = {"spells": "spell scroll", "equipment": "equipment"}

CLASS_ALIASES = {
    "artificer": "artificer",
    "barbarian": "barbarian",
    "bard": "bard",
    "cleric": "cleric",
    "druid": "druid",
    "fighter": "fighter",
    "monk": "monk",
    "paladin": "paladin",
    "ranger": "ranger",
    "rogue": "rogue",
    "sorcerer": "sorcerer",
    "sorc": "sorcerer",
    "warlock": "warlock",
    "wiz": "wizard",
    "wizard": "wizard",
}

PARTY_ROLE_TAGS = {
    "artificer": {"arcane", "support", "utility"},
    "barbarian": {"martial", "frontline"},
    "bard": {"arcane", "social", "support", "stealth"},
    "cleric": {"divine", "support", "frontline"},
    "druid": {"nature", "support", "utility"},
    "fighter": {"martial", "frontline"},
    "monk": {"martial", "stealth", "utility"},
    "paladin": {"divine", "martial", "frontline", "support"},
    "ranger": {"martial", "nature", "stealth", "utility"},
    "rogue": {"martial", "stealth", "social"},
    "sorcerer": {"arcane", "blaster"},
    "warlock": {"arcane", "social"},
    "wizard": {"arcane", "utility"},
}

SLOT_ORDER = [
    "signature item",
    "party utility",
    "surprise scroll",
]

SLOT_PURPOSES = {
    "signature item": "something one character will remember and want to keep",
    "party utility": "something the group will actually use in the next two sessions",
    "surprise scroll": "a weird or useful one-shot reward that changes how the table plays",
}

LOOKUP_TOOL = {
    "name": "lookup_reward",
    "description": "Select one reward candidate by slot, category, and canonical index.",
    "parameters": {
        "type": "object",
        "properties": {
            "slot": {
                "type": "string",
                "enum": SLOT_ORDER,
                "description": "Treasure slot being filled.",
            },
            "category": {
                "type": "string",
                "enum": ["magic-items", "equipment", "spells"],
                "description": "SRD endpoint category for the reward.",
            },
            "index": {
                "type": "string",
                "description": "Canonical SRD index from the candidate list.",
            },
        },
        "required": ["slot", "category", "index"],
    },
}


class PartyMember(BaseModel):
    name: str = Field(description="Character name.")
    character_class: str = Field(description="Normalized DnD class name.")
    level: int = Field(description="Character level from 1 to 20.")


class TreasureReward(BaseModel):
    slot: str = Field(description="Reward slot name.")
    reward_name: str = Field(description="Canonical reward name.")
    reward_type: str = Field(
        description="Reward type such as magic item or spell scroll."
    )
    best_fit: str = Field(description="Who this reward best fits.")
    why_it_fits: str = Field(description="Why it fits this party or session.")
    reveal_text: str = Field(description="1-2 sentence read-aloud reveal.")
    caveats: list[str] = Field(
        description="Rules reminders, attunement notes, or constraints."
    )


class TreasurePacket(BaseModel):
    headline: str = Field(description="Short title for the packet.")
    party_read: str = Field(description="2-3 sentence read on the party and session.")
    rewards: list[TreasureReward] = Field(
        description="Three tailored treasure rewards."
    )
    table_notes: list[str] = Field(
        description="Short DM notes for pacing or follow-up."
    )


@dataclass(frozen=True)
class RewardSeed:
    slot: str
    category: str
    index: str
    hook: str
    tags: frozenset[str]
    moods: frozenset[str]
    min_level: int = 1
    max_level: int = 20


REWARD_SEEDS = [
    RewardSeed(
        slot="signature item",
        category="magic-items",
        index="gauntlets-of-ogre-power",
        hook="A clear martial upgrade for a strength-forward frontliner.",
        tags=frozenset({"martial", "frontline"}),
        moods=frozenset({"generous"}),
        min_level=4,
    ),
    RewardSeed(
        slot="signature item",
        category="magic-items",
        index="bracers-of-archery",
        hook="A clean reward for someone who solves problems with ranged pressure.",
        tags=frozenset({"martial", "utility"}),
        moods=frozenset({"low-magic", "generous"}),
        min_level=3,
    ),
    RewardSeed(
        slot="signature item",
        category="magic-items",
        index="boots-of-elvenkind",
        hook="A stealth reward that feels immediately usable instead of ornamental.",
        tags=frozenset({"stealth"}),
        moods=frozenset({"low-magic"}),
        min_level=2,
    ),
    RewardSeed(
        slot="signature item",
        category="magic-items",
        index="hat-of-disguise",
        hook="A social or infiltration reward with instant roleplay energy.",
        tags=frozenset({"social", "arcane", "stealth"}),
        moods=frozenset({"weird"}),
        min_level=2,
    ),
    RewardSeed(
        slot="signature item",
        category="magic-items",
        index="periapt-of-wound-closure",
        hook="A gritty survivability prize for the character who keeps getting dropped.",
        tags=frozenset({"frontline", "support"}),
        moods=frozenset({"low-magic"}),
        min_level=3,
    ),
    RewardSeed(
        slot="signature item",
        category="magic-items",
        index="driftglobe",
        hook="A compact arcane-feeling relic with exploration value.",
        tags=frozenset({"arcane", "utility"}),
        moods=frozenset({"weird", "low-magic"}),
        min_level=2,
    ),
    RewardSeed(
        slot="party utility",
        category="magic-items",
        index="bag-of-holding",
        hook="The classic utility reward because the table will absolutely use it.",
        tags=frozenset({"utility"}),
        moods=frozenset({"generous", "low-magic"}),
        min_level=1,
    ),
    RewardSeed(
        slot="party utility",
        category="magic-items",
        index="immovable-rod",
        hook="A puzzle-solver that creates stories instead of just numbers.",
        tags=frozenset({"utility"}),
        moods=frozenset({"weird"}),
        min_level=3,
    ),
    RewardSeed(
        slot="party utility",
        category="magic-items",
        index="sending-stones",
        hook="A party-wide utility reward for scouting, splitting up, and panic plans.",
        tags=frozenset({"support", "utility", "social"}),
        moods=frozenset({"generous"}),
        min_level=3,
    ),
    RewardSeed(
        slot="party utility",
        category="magic-items",
        index="lantern-of-revealing",
        hook="Useful when the session tone involves secrets, traps, or hidden threats.",
        tags=frozenset({"utility"}),
        moods=frozenset({"low-magic", "weird"}),
        min_level=2,
    ),
    RewardSeed(
        slot="party utility",
        category="magic-items",
        index="rope-of-climbing",
        hook="A clean exploration reward for vertical or environmental play.",
        tags=frozenset({"utility", "nature"}),
        moods=frozenset({"low-magic"}),
        min_level=2,
    ),
    RewardSeed(
        slot="party utility",
        category="magic-items",
        index="alchemy-jug",
        hook="A whimsical utility reward that keeps paying off in odd ways.",
        tags=frozenset({"utility"}),
        moods=frozenset({"weird"}),
        min_level=2,
    ),
    RewardSeed(
        slot="party utility",
        category="equipment",
        index="climbers-kit",
        hook="A mundane but honest reward when the campaign wants grounded utility.",
        tags=frozenset({"utility", "frontline"}),
        moods=frozenset({"low-magic"}),
        min_level=1,
    ),
    RewardSeed(
        slot="party utility",
        category="equipment",
        index="healers-kit",
        hook="A practical support reward with zero mystery and immediate use.",
        tags=frozenset({"support"}),
        moods=frozenset({"low-magic"}),
        min_level=1,
    ),
    RewardSeed(
        slot="party utility",
        category="equipment",
        index="thieves-tools",
        hook="A grounded infiltration reward for the party member who solves locks and traps.",
        tags=frozenset({"stealth"}),
        moods=frozenset({"low-magic"}),
        min_level=1,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="identify",
        hook="A scroll reward that turns mystery objects into immediate play.",
        tags=frozenset({"arcane", "utility"}),
        moods=frozenset({"low-magic"}),
        min_level=1,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="feather-fall",
        hook="A panic-button scroll for vertical maps and last-second heroics.",
        tags=frozenset({"arcane", "utility"}),
        moods=frozenset({"low-magic"}),
        min_level=1,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="knock",
        hook="A scroll that lets the table skip exactly one lock-shaped headache.",
        tags=frozenset({"arcane", "stealth", "utility"}),
        moods=frozenset({"weird"}),
        min_level=3,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="misty-step",
        hook="A one-shot repositioning reward with immediate tactical drama.",
        tags=frozenset({"arcane", "stealth"}),
        moods=frozenset({"generous"}),
        min_level=3,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="lesser-restoration",
        hook="A support scroll that saves a rough night from spiraling.",
        tags=frozenset({"divine", "support"}),
        moods=frozenset({"low-magic"}),
        min_level=3,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="pass-without-trace",
        hook="A strong table-wide stealth button for the party that never moves quietly enough.",
        tags=frozenset({"nature", "stealth", "support"}),
        moods=frozenset({"generous"}),
        min_level=3,
    ),
    RewardSeed(
        slot="surprise scroll",
        category="spells",
        index="augury",
        hook="A delightfully in-fiction nudge button when the table loves omens.",
        tags=frozenset({"divine", "support", "social"}),
        moods=frozenset({"weird"}),
        min_level=3,
    ),
]

MOCK_DETAILS: dict[tuple[str, str], dict[str, Any]] = {
    ("magic-items", "boots-of-elvenkind"): {
        "name": "Boots of Elvenkind",
        "reward_type": "magic item",
        "category_label": "Wondrous Item",
        "rarity": "Uncommon",
        "desc": [
            "While you wear these boots, your steps make no sound, regardless of the surface you are moving across."
        ],
    },
    ("magic-items", "bag-of-holding"): {
        "name": "Bag of Holding",
        "reward_type": "magic item",
        "category_label": "Wondrous Item",
        "rarity": "Uncommon",
        "desc": [
            "A roomy extradimensional bag that saves every table from arguing about carrying capacity."
        ],
    },
    ("spells", "identify"): {
        "name": "Identify",
        "reward_type": "spell scroll",
        "category_label": "Spell",
        "level": 1,
        "classes": ["bard", "wizard"],
        "desc": [
            "Learn a magic item's properties, whether it needs attunement, and what spells affect it."
        ],
        "ritual": True,
        "concentration": False,
    },
}


def normalize_class_name(raw: str) -> str:
    """Normalize user class labels toward a small stable vocabulary."""
    cleaned = re.sub(r"[^a-z]", "", raw.strip().lower())
    normalized = CLASS_ALIASES.get(cleaned)
    if normalized is None:
        known = ", ".join(sorted(CLASS_ALIASES))
        raise ValueError(f"Unknown class {raw!r}. Known forms include: {known}.")
    return normalized


def parse_party_member(raw: str) -> PartyMember:
    """Parse CLI input in NAME:CLASS:LEVEL form."""
    parts = [part.strip() for part in raw.split(":", 2)]
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"Party members must use NAME:CLASS:LEVEL format, got {raw!r}."
        )
    name, character_class, level_text = parts
    try:
        level = int(level_text)
    except ValueError as exc:
        raise ValueError(f"Level must be an integer in {raw!r}.") from exc
    if not 1 <= level <= 20:
        raise ValueError(f"Level must be between 1 and 20 in {raw!r}.")
    return PartyMember(
        name=name,
        character_class=normalize_class_name(character_class),
        level=level,
    )


def party_tags(party: list[PartyMember]) -> set[str]:
    """Return coarse playstyle tags inferred from the party roster."""
    tags: set[str] = set()
    for member in party:
        tags.update(PARTY_ROLE_TAGS.get(member.character_class, set()))
    return tags or {"utility"}


def average_level(party: list[PartyMember]) -> int:
    """Return the rounded average party level."""
    total = sum(member.level for member in party)
    return max(1, round(total / len(party)))


def spell_level_cap(level: int) -> int:
    """Use a conservative spell level cap for scroll-like rewards."""
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    return 5


def slot_prompt(slot: str) -> str:
    """Return the fixed prompt for one reward slot."""
    return (
        f"Choose the single best reward for the {slot} slot. "
        f"The goal is {SLOT_PURPOSES[slot]}. "
        "Use lookup_reward exactly once with one candidate from that slot's list. "
        "Prefer a reward that matches the party and the session summary. "
        "Do not explain your choice."
    )


def build_packet_prompt(reward_mood: str, tone: str) -> str:
    """Return the synthesis prompt for the final treasure packet."""
    return (
        "Write a compact treasure packet for this DnD party. "
        f"The tone is {tone} and the reward mood is {reward_mood}. "
        "Stay grounded in the normalized reward facts. "
        "Make the reveal text flavorful but brief. "
        "Put rules reminders, attunement notes, class limitations, or odd edge cases in caveats instead of hiding them in prose."
    )


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


def first_valid_selection(
    slot: str,
    tool_calls: list[dict[str, Any]],
    allowed: set[tuple[str, str]],
) -> tuple[str, str] | None:
    """Return the first valid category/index pair from tool calls."""
    for call in tool_calls:
        args = parse_tool_arguments(call.get("arguments"))
        if args.get("slot") != slot:
            continue
        category = str(args.get("category", "")).strip()
        index = str(args.get("index", "")).strip()
        if (category, index) in allowed:
            return category, index
    return None


def summarize_party(party: list[PartyMember]) -> list[str]:
    """Return compact strings for display and source context."""
    return [
        f"{member.name} ({member.character_class.title()} {member.level})"
        for member in party
    ]


def best_recipient(seed: RewardSeed, party: list[PartyMember]) -> str:
    """Choose a plausible best-fit recipient for deterministic fallbacks."""
    tags = set(seed.tags)
    ranked = sorted(
        party,
        key=lambda member: (
            len(PARTY_ROLE_TAGS.get(member.character_class, set()) & tags),
            member.level,
        ),
        reverse=True,
    )
    return ranked[0].name if ranked else "the party"


def score_seed(seed: RewardSeed, *, tags: set[str], mood: set[str], level: int) -> int:
    """Return a small heuristic score for seed ranking."""
    score = 1
    overlap = len(tags & set(seed.tags))
    score += overlap * 3
    score += len(mood & set(seed.moods)) * 2
    if seed.min_level <= level <= seed.max_level:
        score += 2
    if level < seed.min_level:
        score -= 4
    return score


def fallback_spell_seed(slot: str, level: int) -> RewardSeed:
    """Return a low-risk backup spell seed if filtering gets too tight."""
    return RewardSeed(
        slot=slot,
        category="spells",
        index="identify",
        hook="A reliable scroll reward that supports a curious party.",
        tags=frozenset({"arcane", "utility"}),
        moods=frozenset({"low-magic"}),
        min_level=1,
        max_level=max(level, 1),
    )


def build_candidate_catalog(
    party: list[PartyMember],
    *,
    reward_mood: str,
    available: dict[str, dict[str, str]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], RewardSeed]]:
    """Build slot-specific candidate lists from curated seeds and live indexes."""
    tags = party_tags(party)
    avg_level = average_level(party)
    mood = {t for t in re.split(r"[\s,/+-]+", reward_mood.lower()) if t}
    spell_cap = spell_level_cap(avg_level)
    by_slot: dict[str, list[dict[str, Any]]] = {slot: [] for slot in SLOT_ORDER}
    seed_lookup: dict[tuple[str, str], RewardSeed] = {}

    for seed in REWARD_SEEDS:
        if seed.index not in available.get(seed.category, {}):
            continue
        if seed.category == "spells" and seed.min_level > spell_cap:
            continue
        score = score_seed(seed, tags=tags, mood=mood, level=avg_level)
        entry = {
            "category": seed.category,
            "index": seed.index,
            "name": available[seed.category][seed.index],
            "reward_type": REWARD_TYPE_LABELS.get(seed.category, "magic item"),
            "hook": seed.hook,
            "score": score,
        }
        by_slot[seed.slot].append(entry)
        seed_lookup[(seed.category, seed.index)] = seed

    for slot in SLOT_ORDER:
        ranked = sorted(
            by_slot[slot],
            key=lambda item: (int(item["score"]), str(item["name"])),
            reverse=True,
        )
        trimmed = ranked[:MAX_SLOT_CANDIDATES]
        if not trimmed and slot == "surprise scroll":
            fallback = fallback_spell_seed(slot, spell_cap)
            trimmed = [
                {
                    "category": fallback.category,
                    "index": fallback.index,
                    "name": "Identify",
                    "reward_type": REWARD_TYPE_LABELS.get(
                        fallback.category, "magic item"
                    ),
                    "hook": fallback.hook,
                    "score": 1,
                }
            ]
            seed_lookup[(fallback.category, fallback.index)] = fallback
        by_slot[slot] = trimmed

    return by_slot, seed_lookup


def request_json(url: str) -> dict[str, Any]:
    """Fetch one JSON document from the SRD API."""
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "pollux-cookbook/treasure-tailor",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                return {}
            return cast("dict[str, Any]", payload)
    except HTTPError as exc:
        raise RuntimeError(f"D&D API HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"D&D API request failed for {url}: {exc.reason}") from exc


def fetch_index_catalog(category: str) -> dict[str, str]:
    """Fetch the name lookup table for one SRD category."""
    payload = request_json(f"{API_BASE}/{category}")
    results = payload.get("results", [])
    catalog: dict[str, str] = {}
    if not isinstance(results, list):
        return catalog
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        name = item.get("name")
        if isinstance(index, str) and isinstance(name, str):
            catalog[index] = name
    return catalog


def normalize_detail(category: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce verbose API payloads into a compact normalized fact block."""
    desc = payload.get("desc")
    desc_lines = (
        [line for line in desc if isinstance(line, str)]
        if isinstance(desc, list)
        else []
    )
    base = {
        "category": category,
        "name": str(payload.get("name", "Unknown reward")),
        "reward_type": REWARD_TYPE_LABELS.get(category, "magic item"),
        "desc": desc_lines[:2],
    }
    if category == "magic-items":
        rarity = payload.get("rarity", {})
        equipment_category = payload.get("equipment_category", {})
        return {
            **base,
            "category_label": str(equipment_category.get("name", "Magic Item")),
            "rarity": str(rarity.get("name", "Unknown")),
        }
    if category == "equipment":
        equipment_category = payload.get("equipment_category", {})
        cost = payload.get("cost", {})
        cost_text = ""
        if isinstance(cost, dict):
            quantity = cost.get("quantity")
            unit = cost.get("unit")
            if quantity is not None and unit is not None:
                cost_text = f"{quantity} {unit}"
        return {
            **base,
            "category_label": str(equipment_category.get("name", "Equipment")),
            "cost": cost_text,
        }
    classes = payload.get("classes", [])
    class_names = [
        str(item.get("name", "")).lower()
        for item in classes
        if isinstance(item, dict) and item.get("name")
    ]
    return {
        **base,
        "category_label": "Spell",
        "level": int(payload.get("level", 0) or 0),
        "school": str(payload.get("school", {}).get("name", "")),
        "ritual": bool(payload.get("ritual", False)),
        "concentration": bool(payload.get("concentration", False)),
        "classes": class_names,
    }


def fetch_reward_detail(category: str, index: str) -> dict[str, Any]:
    """Fetch one normalized reward detail block."""
    payload = request_json(f"{API_BASE}/{category}/{index}")
    return normalize_detail(category, payload)


def mock_reward_detail(category: str, index: str) -> dict[str, Any]:
    """Return canned detail blocks for mock mode."""
    detail = MOCK_DETAILS.get((category, index))
    if detail is not None:
        return detail
    return {
        "name": index.replace("-", " ").title(),
        "reward_type": REWARD_TYPE_LABELS.get(category, "magic item"),
        "category_label": "Reward",
        "desc": ["A credible mock reward used to validate the treasure packet flow."],
    }


def reward_fact_block(
    seed: RewardSeed,
    detail: dict[str, Any],
    *,
    party: list[PartyMember],
) -> dict[str, Any]:
    """Combine the curated seed and fetched detail for synthesis."""
    return {
        "slot": seed.slot,
        "reward_name": detail["name"],
        "reward_type": detail["reward_type"],
        "best_fit_hint": best_recipient(seed, party),
        "hook": seed.hook,
        "fit_tags": sorted(seed.tags),
        **detail,
    }


def reward_caveats(detail: dict[str, Any]) -> list[str]:
    """Derive visible caveats for deterministic fallbacks."""
    caveats: list[str] = []
    desc_text = " ".join(
        line for line in detail.get("desc", []) if isinstance(line, str)
    ).lower()
    if "attunement" in desc_text:
        caveats.append("Check attunement before handing it out.")
    if detail.get("reward_type") == "spell scroll":
        classes = detail.get("classes", [])
        if classes:
            caveats.append(
                "Spell list fit matters: "
                + ", ".join(str(name).title() for name in classes)
            )
        if detail.get("concentration"):
            caveats.append("Concentration applies if the spell normally needs it.")
    if detail.get("cost"):
        caveats.append(
            f"Grounded item, not magic: treat it like gear worth {detail['cost']}."
        )
    if not caveats:
        caveats.append("No unusual caveat surfaced in the normalized rules text.")
    return caveats


def fallback_packet(
    party: list[PartyMember],
    *,
    summary: str,
    tone: str,
    reward_mood: str,
    reward_facts: list[dict[str, Any]],
) -> TreasurePacket:
    """Build a stable treasure packet when structured output is unavailable."""
    rewards = [
        TreasureReward(
            slot=fact["slot"],
            reward_name=fact["reward_name"],
            reward_type=fact["reward_type"],
            best_fit=str(fact["best_fit_hint"]),
            why_it_fits=(
                f"{fact['reward_name']} fits {fact['best_fit_hint']} and supports a "
                f"{tone} session with a {reward_mood} reward mood."
            ),
            reveal_text=(
                f"Inside the spoils, the party finds {fact['reward_name']}: "
                f"{fact['hook']}"
            ),
            caveats=reward_caveats(fact),
        )
        for fact in reward_facts
    ]
    return TreasurePacket(
        headline=f"{tone.title()} treasure packet",
        party_read=(
            f"This party is operating around level {average_level(party)} with a mix of "
            f"{', '.join(sorted(party_tags(party))[:3])}. "
            f"Session summary: {summary}"
        ),
        rewards=rewards,
        table_notes=[
            "Put the most character-specific reward on the table first.",
            "Let the utility reward spark group planning before you move on.",
            "Use the surprise scroll as the odd little extra, not the headline.",
        ],
    )


async def load_live_catalogs() -> dict[str, dict[str, str]]:
    """Fetch the small set of live SRD indexes used by the recipe."""
    equipment, magic_items, spells = await asyncio.gather(
        asyncio.to_thread(fetch_index_catalog, "equipment"),
        asyncio.to_thread(fetch_index_catalog, "magic-items"),
        asyncio.to_thread(fetch_index_catalog, "spells"),
    )
    return {
        "equipment": equipment,
        "magic-items": magic_items,
        "spells": spells,
    }


def mock_catalogs() -> dict[str, dict[str, str]]:
    """Return a tiny stable catalog for mock mode."""
    return {
        "equipment": {
            "climbers-kit": "Climber's Kit",
            "healers-kit": "Healer's Kit",
            "thieves-tools": "Thieves' Tools",
        },
        "magic-items": {
            "bag-of-holding": "Bag of Holding",
            "boots-of-elvenkind": "Boots of Elvenkind",
            "driftglobe": "Driftglobe",
        },
        "spells": {
            "identify": "Identify",
            "feather-fall": "Feather Fall",
            "knock": "Knock",
        },
    }


async def select_rewards(
    party: list[PartyMember],
    *,
    summary: str,
    tone: str,
    reward_mood: str,
    config: Config,
    available: dict[str, dict[str, str]],
) -> tuple[list[RewardSeed], ResultEnvelope]:
    """Use fan-out tool calls to choose one reward for each slot."""
    candidates_by_slot, seed_lookup = build_candidate_catalog(
        party, reward_mood=reward_mood, available=available
    )
    context = {
        "party": [member.model_dump() for member in party],
        "party_snapshot": summarize_party(party),
        "session_summary": summary,
        "tone": tone,
        "reward_mood": reward_mood,
        "slots": [
            {
                "slot": slot,
                "purpose": SLOT_PURPOSES[slot],
                "candidates": candidates_by_slot[slot],
            }
            for slot in SLOT_ORDER
        ],
    }
    selection_env = await run_many(
        [slot_prompt(slot) for slot in SLOT_ORDER],
        sources=[Source.from_json(context, identifier="treasure-catalog")],
        config=config,
        options=Options(tools=[LOOKUP_TOOL], tool_choice={"name": "lookup_reward"}),
    )

    raw_tool_calls = selection_env.get("tool_calls", [])
    chosen: list[RewardSeed] = []
    for idx, slot in enumerate(SLOT_ORDER):
        slot_calls = raw_tool_calls[idx] if idx < len(raw_tool_calls) else []
        allowed = {
            (str(item["category"]), str(item["index"]))
            for item in candidates_by_slot[slot]
        }
        picked = first_valid_selection(slot, slot_calls, allowed)
        if picked is None:
            fallback = candidates_by_slot[slot][0]
            picked = str(fallback["category"]), str(fallback["index"])
        chosen.append(seed_lookup[picked])

    selection_env.setdefault("metrics", {})
    selection_env["metrics"]["tool_calls_seen"] = sum(
        len(calls) for calls in raw_tool_calls if isinstance(calls, list)
    )
    return chosen, selection_env


async def run_mock_flow(
    party: list[PartyMember],
    *,
    summary: str,
    tone: str,
    reward_mood: str,
    config: Config,
) -> tuple[TreasurePacket, list[dict[str, Any]], ResultEnvelope]:
    """Exercise the bounded flow with deterministic mock rewards."""
    available = mock_catalogs()
    selected, selection_env = await select_rewards(
        party,
        summary=summary,
        tone=tone,
        reward_mood=reward_mood,
        config=config,
        available=available,
    )
    reward_facts = [
        reward_fact_block(
            seed, mock_reward_detail(seed.category, seed.index), party=party
        )
        for seed in selected
    ]
    packet = fallback_packet(
        party,
        summary=summary,
        tone=tone,
        reward_mood=reward_mood,
        reward_facts=reward_facts,
    )
    return packet, reward_facts, selection_env


async def run_real_flow(
    party: list[PartyMember],
    *,
    summary: str,
    tone: str,
    reward_mood: str,
    config: Config,
) -> tuple[TreasurePacket, list[dict[str, Any]], ResultEnvelope]:
    """Run live selection and synthesis against the SRD API."""
    available = await load_live_catalogs()
    selected, selection_env = await select_rewards(
        party,
        summary=summary,
        tone=tone,
        reward_mood=reward_mood,
        config=config,
        available=available,
    )

    details = await asyncio.gather(
        *[
            asyncio.to_thread(fetch_reward_detail, seed.category, seed.index)
            for seed in selected
        ]
    )
    reward_facts = [
        reward_fact_block(seed, detail, party=party)
        for seed, detail in zip(selected, details, strict=True)
    ]
    packet_env = await run(
        build_packet_prompt(reward_mood, tone),
        source=Source.from_json(
            {
                "party": [member.model_dump() for member in party],
                "party_snapshot": summarize_party(party),
                "session_summary": summary,
                "tone": tone,
                "reward_mood": reward_mood,
                "rewards": reward_facts,
            },
            identifier="treasure-facts",
        ),
        config=config,
        options=Options(response_schema=TreasurePacket),
    )
    structured = packet_env.get("structured", [])
    first = structured[0] if isinstance(structured, list) and structured else None
    packet = (
        first
        if isinstance(first, TreasurePacket)
        else fallback_packet(
            party,
            summary=summary,
            tone=tone,
            reward_mood=reward_mood,
            reward_facts=reward_facts,
        )
    )
    combined = merged_usage(selection_env, packet_env)
    combined.setdefault("metrics", {})
    combined["metrics"]["tool_calls_seen"] = selection_env.get("metrics", {}).get(
        "tool_calls_seen", 0
    )
    combined["metrics"]["reward_count"] = len(reward_facts)
    return packet, reward_facts, combined


def print_party_snapshot(party: list[PartyMember], *, summary: str, tone: str) -> None:
    """Print the roster and session setup."""
    print_section("Party snapshot")
    print_kv_rows(
        [
            ("Party size", len(party)),
            ("Average level", average_level(party)),
            ("Tone", tone),
            ("Summary", summary),
        ]
    )
    print_section("Party")
    for member in party:
        print(f"- {member.name}: {member.character_class.title()} {member.level}")


def print_reward_facts(reward_facts: list[dict[str, Any]]) -> None:
    """Print the normalized reward facts that anchor the packet."""
    print_section("Normalized rewards")
    for fact in reward_facts:
        print(
            f"- {fact['slot']}: {fact['reward_name']} ({fact['reward_type']}) "
            f"| best fit hint={fact['best_fit_hint']}"
        )


def print_packet(packet: TreasurePacket) -> None:
    """Print the final packet in a compact DM-friendly format."""
    print_section("Treasure packet")
    print(f"  {packet.headline}")
    print(f"  {packet.party_read}")

    print_section("Rewards")
    for reward in packet.rewards:
        print(f"- {reward.slot}: {reward.reward_name} ({reward.reward_type})")
        print(f"  Best fit: {reward.best_fit}")
        print(f"  Why it fits: {reward.why_it_fits}")
        print(f"  Reveal: {reward.reveal_text}")
        print("  Caveats:")
        for caveat in reward.caveats:
            print(f"  - {caveat}")

    print_section("Table notes")
    for note in packet.table_notes:
        print(f"- {note}")


async def main_async(
    party: list[PartyMember],
    *,
    summary: str,
    tone: str,
    reward_mood: str,
    config: Config,
) -> None:
    if config.use_mock:
        packet, reward_facts, envelope = await run_mock_flow(
            party,
            summary=summary,
            tone=tone,
            reward_mood=reward_mood,
            config=config,
        )
    else:
        packet, reward_facts, envelope = await run_real_flow(
            party,
            summary=summary,
            tone=tone,
            reward_mood=reward_mood,
            config=config,
        )

    print_party_snapshot(party, summary=summary, tone=tone)
    print_section("Treasure snapshot")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Reward mood", reward_mood),
            ("Rewards", len(reward_facts)),
            ("Tool lookups", envelope.get("metrics", {}).get("tool_calls_seen", 0)),
        ]
    )
    print_reward_facts(reward_facts)
    print_packet(packet)
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: swap the session summary and watch the signature reward change.",
            "Next: fork the seed list toward your own setting or house-rule economy.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn party notes and SRD lookups into a tailored treasure packet.",
    )
    parser.add_argument(
        "--party-member",
        action="append",
        required=True,
        help='Party member in NAME:CLASS:LEVEL form, for example "Nyx:rogue:5". Repeat for each member.',
    )
    parser.add_argument(
        "--summary",
        required=True,
        help="Short session or campaign summary that tells the recipe what just happened.",
    )
    parser.add_argument(
        "--tone",
        default="adventurous",
        help='Campaign or scene tone, for example "mysterious" or "dungeon-delving".',
    )
    parser.add_argument(
        "--reward-mood",
        default="useful with a little weirdness",
        help='Reward vibe, for example "low-magic", "weird", or "generous".',
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    try:
        party = [parse_party_member(raw) for raw in args.party_member]
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not PARTY_MIN_SIZE <= len(party) <= PARTY_MAX_SIZE:
        raise SystemExit(
            f"Provide between {PARTY_MIN_SIZE} and {PARTY_MAX_SIZE} party members."
        )

    config = build_config_or_exit(args)
    print_header("Treasure Tailor", config=config)
    asyncio.run(
        main_async(
            party,
            summary=args.summary.strip(),
            tone=args.tone.strip() or "adventurous",
            reward_mood=args.reward_mood.strip() or "useful with a little weirdness",
            config=config,
        )
    )


if __name__ == "__main__":
    main()
