#!/usr/bin/env python3
"""Recipe: Turn a short Pokemon roster into a scouting report.

Problem:
    Team ideas are easy to imagine and annoying to sanity-check. You want a
    quick report that starts from canonical facts instead of fuzzy memory.

When to use:
    - You have 3-6 Pokemon and want a fast read on overlap, pressure, and gaps.
    - You want a small tool-calling example that stays bounded.

When not to use:
    - You want an open-ended team-building agent.
    - You need matchup-calculator precision for competitive play.

Run:
    python -m cookbook projects/pokedex-analyst pikachu gyarados ferrothorn --no-mock

Success check:
    - Every roster slot resolves to a canonical Pokemon entry.
    - Output includes strengths, weak spots, and concrete next moves.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
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
from pollux import (
    Config,
    Environment,
    Input,
    Source,
    ToolDeclaration,
    ToolResult,
    interact,
    run,
)

if TYPE_CHECKING:
    from pollux import Output
    from pollux.interaction import ToolCall


API_BASE = "https://pokeapi.co/api/v2"
MAX_ROSTER_SIZE = 6
MIN_ROSTER_SIZE = 3

LOOKUP_TOOL = {
    "name": "lookup_pokemon",
    "description": "Look up canonical Pokemon facts from PokeAPI.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Pokemon name using the closest canonical PokeAPI spelling.",
            }
        },
        "required": ["name"],
    },
}


# -- Schemas ----------------------------------------------------------------


class RosterSlot(BaseModel):
    name: str = Field(description="Canonical Pokemon name.")
    types: list[str] = Field(description="Pokemon typing.")
    likely_role: str = Field(description="Short role guess for this team.")


class TeamReport(BaseModel):
    title: str = Field(description="Short scouting report title.")
    overview: str = Field(description="2-3 sentence team read.")
    roster: list[RosterSlot] = Field(description="Roster summary with likely roles.")
    strengths: list[str] = Field(description="3-5 concrete strengths.")
    weak_spots: list[str] = Field(description="3-5 pressure points or overlap risks.")
    recommendations: list[str] = Field(
        description="2-4 concrete next moves, swaps, or additions."
    )


# -- Mock fixtures ----------------------------------------------------------

MOCK_FIXTURES: dict[str, dict[str, Any]] = {
    "pikachu": {
        "name": "pikachu",
        "types": ["electric"],
        "abilities": ["static", "lightning-rod"],
        "base_stats": {
            "hp": 35,
            "attack": 55,
            "defense": 40,
            "special-attack": 50,
            "special-defense": 50,
            "speed": 90,
        },
    },
    "gyarados": {
        "name": "gyarados",
        "types": ["water", "flying"],
        "abilities": ["intimidate", "moxie"],
        "base_stats": {
            "hp": 95,
            "attack": 125,
            "defense": 79,
            "special-attack": 60,
            "special-defense": 100,
            "speed": 81,
        },
    },
    "ferrothorn": {
        "name": "ferrothorn",
        "types": ["grass", "steel"],
        "abilities": ["iron-barbs", "anticipation"],
        "base_stats": {
            "hp": 74,
            "attack": 94,
            "defense": 131,
            "special-attack": 54,
            "special-defense": 116,
            "speed": 20,
        },
    },
}


# -- Helpers ----------------------------------------------------------------


def normalize_lookup_name(name: str) -> str:
    """Normalize a free-form Pokemon name toward PokeAPI spellings."""
    cleaned = name.strip().lower()
    cleaned = cleaned.replace("♀", "-f").replace("♂", "-m")
    cleaned = cleaned.replace("é", "e")
    cleaned = re.sub(r"[.'':]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    return re.sub(r"-+", "-", cleaned)


def plan_lookup_names(roster: list[str], tool_calls: tuple[ToolCall, ...]) -> list[str]:
    """Map tool-call requests back onto the roster order."""
    planned: list[str] = []
    for idx, raw_name in enumerate(roster):
        call = tool_calls[idx] if idx < len(tool_calls) else None
        requested = (
            call.arguments.get("name")
            if (call is not None and isinstance(call.arguments, dict))
            else None
        )
        planned.append(str(requested).strip() if requested else raw_name)
    return planned


def fetch_pokemon(name: str) -> dict[str, Any]:
    """Fetch canonical facts for one Pokemon from PokeAPI."""
    slug = normalize_lookup_name(name)
    url = f"{API_BASE}/pokemon/{quote(slug)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "pollux-cookbook/pokedex-analyst",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"Pokemon {name!r} not found on PokeAPI. Try a more canonical spelling."
            ) from exc
        raise RuntimeError(f"PokeAPI HTTP {exc.code} for {name!r}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"PokeAPI request failed for {name!r}: {exc.reason}"
        ) from exc

    return {
        "name": str(data.get("name", name)),
        "types": [t["type"]["name"] for t in data.get("types", [])],
        "abilities": [
            a["ability"]["name"]
            for a in data.get("abilities", [])
            if not a.get("is_hidden")
        ],
        "base_stats": {
            s["stat"]["name"]: int(s["base_stat"]) for s in data.get("stats", [])
        },
    }


def mock_profiles(roster: list[str]) -> list[dict[str, Any]]:
    """Return canned profiles that match the live fetch shape."""
    profiles: list[dict[str, Any]] = []
    for raw_name in roster:
        key = normalize_lookup_name(raw_name)
        fixture = MOCK_FIXTURES.get(key)
        if fixture is not None:
            profiles.append(dict(fixture))
        else:
            profiles.append(
                {
                    "name": key,
                    "types": ["normal"],
                    "abilities": ["adaptability"],
                    "base_stats": {
                        "hp": 80,
                        "attack": 80,
                        "defense": 80,
                        "special-attack": 80,
                        "special-defense": 80,
                        "speed": 80,
                    },
                }
            )
    return profiles


def fallback_report(
    profiles: list[dict[str, Any]],
    *,
    battle_format: str,
) -> TeamReport:
    """Build a stable report shape when structured output is unavailable."""
    return TeamReport(
        title=f"{battle_format} scouting report",
        overview=f"A {battle_format} roster with readable identity and room to refine.",
        roster=[
            RosterSlot(
                name=p["name"].replace("-", " ").title(),
                types=p["types"],
                likely_role="see analysis",
            )
            for p in profiles
        ],
        strengths=[
            "The roster covers multiple type lanes.",
            "Several members bring distinct offensive profiles.",
        ],
        weak_spots=[
            "Type overlap may concentrate shared weaknesses.",
            "Role clarity improves once a primary win condition is chosen.",
        ],
        recommendations=[
            "Identify the main win condition and build support around it.",
            "Check for a shared weakness that one addition could patch.",
        ],
    )


# -- Prompts ----------------------------------------------------------------


def build_lookup_prompt(roster: list[str], battle_format: str) -> str:
    """Return the bounded tool-planning prompt."""
    joined = ", ".join(roster)
    return (
        f"You are preparing a Pokemon scouting report for {battle_format}. "
        f"Roster: {joined}. "
        "Call lookup_pokemon exactly once for each roster slot, in order. "
        "Use the closest canonical PokeAPI spelling. Do not explain anything."
    )


def build_report_prompt(battle_format: str) -> str:
    """Return the structured-output prompt for the final report."""
    return (
        f"Write a concise scouting report for this {battle_format} roster. "
        "Use the normalized facts faithfully. Be specific about overlap, pressure, "
        "and next moves. Avoid hype and avoid pretending this is a perfect simulator."
    )


# -- Presentation -----------------------------------------------------------


def print_roster_snapshot(profiles: list[dict[str, Any]]) -> None:
    """Print the normalized roster in one compact section."""
    print_section("Normalized roster")
    for p in profiles:
        display = p["name"].replace("-", " ").title()
        types = "/".join(p["types"])
        print(f"- {display}: {types}")


def print_report(report: TeamReport) -> None:
    """Print the final structured scouting report."""
    print_section("Overview")
    print(f"  {report.overview}")

    print_section("Roster roles")
    for slot in report.roster:
        print(f"- {slot.name}: {'/'.join(slot.types)} | {slot.likely_role}")

    print_section("Strengths")
    for item in report.strengths:
        print(f"- {item}")

    print_section("Weak spots")
    for item in report.weak_spots:
        print(f"- {item}")

    print_section("Recommendations")
    for item in report.recommendations:
        print(f"- {item}")


# -- Flows ------------------------------------------------------------------


async def run_mock_flow(
    roster: list[str],
    *,
    battle_format: str,
    config: Config,
) -> tuple[TeamReport, list[dict[str, Any]], Output]:
    """Build a mock report while still exercising one Pollux call."""
    profiles = mock_profiles(roster)
    envelope = await run(
        "Give one sentence about this roster.",
        source=Source.from_json(
            {"battle_format": battle_format, "pokemon": profiles},
            identifier="mock-roster",
        ),
        config=config,
    )
    report = fallback_report(profiles, battle_format=battle_format)
    return report, profiles, envelope


async def run_real_flow(
    roster: list[str],
    *,
    battle_format: str,
    config: Config,
) -> tuple[TeamReport, list[dict[str, Any]], Output]:
    """Use tool calling for lookups, then synthesize a structured report."""
    lookup_decl = ToolDeclaration(
        name=LOOKUP_TOOL["name"],
        description=LOOKUP_TOOL["description"],
        parameters=LOOKUP_TOOL["parameters"],
    )
    env = Environment(tools=[lookup_decl])
    prompt = build_lookup_prompt(roster, battle_format)

    # Turn 1: request the lookup tool calls
    out = await interact(
        env,
        Input(content=prompt),
        config=config,
        tool_choice={"name": "lookup_pokemon"},
    )
    tool_calls = out.tool_calls
    lookup_names = plan_lookup_names(roster, tool_calls)

    # Fetch canonical facts from PokeAPI and build tool results
    profiles: list[dict[str, Any]] = []
    results: list[ToolResult] = []
    for idx, tc in enumerate(tool_calls):
        name = lookup_names[idx] if idx < len(lookup_names) else tc.id
        data = await asyncio.to_thread(fetch_pokemon, name)
        profiles.append(data)
        results.append(ToolResult(call_id=tc.id, content=json.dumps(data)))

    # Turn 2: continuation with tool results, expecting a structured TeamReport
    final = await interact(
        env,
        Input(continuation=out.continuation, tool_results=results),
        config=config,
        output=TeamReport,
    )

    report = final.structured
    if not isinstance(report, TeamReport):
        report = fallback_report(profiles, battle_format=battle_format)

    import dataclasses

    from pollux.interaction.output import Diagnostics, Metrics

    merged_u = merged_usage(out, final)
    merged_m = Metrics(
        duration_s=out.metrics.duration_s + final.metrics.duration_s,
        n_calls=out.metrics.n_calls + final.metrics.n_calls,
        cache_used=out.metrics.cache_used or final.metrics.cache_used,
        cache_mode=final.metrics.cache_mode,
        cache_hit=out.metrics.cache_hit or final.metrics.cache_hit,
        finish_reason=final.metrics.finish_reason,
        completion_status=final.metrics.completion_status,
    )
    final = dataclasses.replace(
        final,
        usage=merged_u,
        metrics=merged_m,
        diagnostics=Diagnostics(raw={"tool_calls_seen": len(tool_calls)}),
    )
    return report, profiles, final


# -- Main -------------------------------------------------------------------


async def main_async(
    roster: list[str],
    *,
    battle_format: str,
    config: Config,
) -> None:
    if config.use_mock:
        report, profiles, envelope = await run_mock_flow(
            roster,
            battle_format=battle_format,
            config=config,
        )
    else:
        report, profiles, envelope = await run_real_flow(
            roster,
            battle_format=battle_format,
            config=config,
        )

    tool_lookups = 0
    if envelope.diagnostics and envelope.diagnostics.raw:
        tool_lookups = envelope.diagnostics.raw.get("tool_calls_seen", 0)

    print_section("Team snapshot")
    print_kv_rows(
        [
            ("Status", envelope.metrics.completion_status),
            ("Format", battle_format),
            ("Roster size", len(roster)),
            ("Tool lookups", tool_lookups),
        ]
    )
    print_roster_snapshot(profiles)
    print_report(report)
    print_usage(envelope)

    print_learning_hints(
        [
            "Next: swap one roster slot and compare how the weak spots change.",
            "Next: tighten the report prompt toward your own battle format or house rules.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn a short Pokemon roster into a scouting report "
        "with tool lookups and structured output.",
    )
    parser.add_argument(
        "roster",
        nargs="+",
        help="3-6 Pokemon names. Quote names with spaces, for example 'Mr Mime'.",
    )
    parser.add_argument(
        "--battle-format",
        default="casual singles",
        help="Format or vibe to analyze for, for example 'VGC doubles' or 'casual singles'.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    roster = [name.strip() for name in args.roster if name.strip()]
    if not MIN_ROSTER_SIZE <= len(roster) <= MAX_ROSTER_SIZE:
        raise SystemExit(
            f"Provide between {MIN_ROSTER_SIZE} and {MAX_ROSTER_SIZE} Pokemon names."
        )

    config = build_config_or_exit(args)
    print_header("PokeDex Analyst", config=config)
    asyncio.run(
        main_async(
            roster,
            battle_format=args.battle_format.strip() or "casual singles",
            config=config,
        )
    )


if __name__ == "__main__":
    main()
