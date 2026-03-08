#!/usr/bin/env python3
"""Recipe: Turn one paper into a workshop packet you can actually use.

Problem:
    A paper summary is not enough when you need to lead a discussion. You need
    a compact packet that helps a group talk, question, and act.

When to use:
    - You are preparing a reading group, seminar, or journal club.
    - You want one paper to produce several discussion-ready outputs.

When not to use:
    - You only need a quick summary (use analyze-single-paper).
    - You need a deep research workflow across many papers.

Run:
    python -m cookbook projects/paper-to-workshop-kit --arxiv 2301.07041 --no-mock
    python -m cookbook projects/paper-to-workshop-kit --input path/to/paper.pdf

Success check:
    - Output includes a hook, slide outline, questions, objections, and actions.
    - Cache status is visible when the provider supports persistent caching.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from cookbook.utils.demo_inputs import (
    DEFAULT_MEDIA_DEMO_DIR,
    DEFAULT_PAPER_DEMO_FILE,
    resolve_file_or_exit,
)
from cookbook.utils.presentation import (
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit, merged_usage
from pollux import Config, Options, Source, create_cache, run_many

if TYPE_CHECKING:
    from pollux.cache import CacheHandle
    from pollux.result import ResultEnvelope

DEFAULT_AUDIENCE = "reading group"


class SkepticalObjection(BaseModel):
    objection: str = Field(description="A concise skeptical objection.")
    why_it_matters: str = Field(description="Why the group should take it seriously.")


class WorkshopKit(BaseModel):
    title: str = Field(description="A short, human-readable paper title.")
    opening_hook: str = Field(
        description="A 1-2 sentence opening to start the workshop."
    )
    slide_outline: list[str] = Field(
        description="5-8 slide titles with brief speaker cues."
    )
    discussion_questions: list[str] = Field(
        description="4-6 open discussion questions."
    )
    skeptical_objections: list[SkepticalObjection] = Field(
        description="2-4 skeptical objections with why they matter."
    )
    action_items: list[str] = Field(
        description="3-5 concrete follow-up ideas for the next week."
    )


def build_prompts(audience: str) -> list[tuple[str, str]]:
    """Return the fixed section prompts for the workshop packet."""
    return [
        (
            "Opening hook",
            (
                f"Write a 1-2 sentence opening hook for a {audience}. "
                "Explain why this paper is worth discussing without hype."
            ),
        ),
        (
            "Slide outline",
            (
                f"Draft a 6-slide outline for a {audience}. "
                "Keep each slide title concrete and add a short speaker cue."
            ),
        ),
        (
            "Discussion questions",
            (
                f"Write 5 discussion questions for a {audience}. "
                "Prefer questions that expose assumptions, tradeoffs, or gaps."
            ),
        ),
        (
            "Skeptical objections",
            (
                "List 3 skeptical reviewer objections. "
                "For each one, explain in one sentence why it matters."
            ),
        ),
        (
            "Next-week actions",
            (
                f"List 4 concrete follow-up actions a {audience} could try next week. "
                "Keep them specific and realistically scoped."
            ),
        ),
    ]


def should_use_cache(config: Config, *, wants_cache: bool) -> tuple[bool, str]:
    """Return whether to use persistent caching and how to describe the choice."""
    if not wants_cache:
        return False, "disabled"
    if config.use_mock or config.provider == "gemini":
        return True, "enabled"
    return False, f"skipped (provider={config.provider} has no persistent cache)"


def normalize_lines(text: str) -> list[str]:
    """Turn model text into a compact list of display lines."""
    items: list[str] = []
    for raw in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", raw).strip()
        if cleaned:
            items.append(cleaned)
    if items:
        return items
    clipped = text.strip()
    return [clipped] if clipped else []


def build_notes(section_answers: list[tuple[str, str]]) -> str:
    """Assemble section outputs into one draft note bundle."""
    blocks: list[str] = []
    for label, answer in section_answers:
        blocks.append(f"{label}\n{answer.strip()}")
    return "\n\n".join(blocks)


def fallback_packet(
    *, source_label: str, section_answers: list[tuple[str, str]]
) -> WorkshopKit:
    """Build a packet from raw section answers when structured output fails."""
    by_label = dict(section_answers)
    return WorkshopKit(
        title=Path(source_label).stem.replace("-", " ").replace("_", " ").strip()
        or source_label,
        opening_hook=by_label.get("Opening hook", "").strip(),
        slide_outline=normalize_lines(by_label.get("Slide outline", ""))[:6],
        discussion_questions=normalize_lines(by_label.get("Discussion questions", ""))[
            :5
        ],
        skeptical_objections=[
            SkepticalObjection(objection=line, why_it_matters="")
            for line in normalize_lines(by_label.get("Skeptical objections", ""))[:3]
        ],
        action_items=normalize_lines(by_label.get("Next-week actions", ""))[:4],
    )


def mock_packet(*, source_label: str, audience: str) -> WorkshopKit:
    """Return a credible packet shape for mock-mode first runs."""
    title = Path(source_label).stem.replace("-", " ").replace("_", " ").strip()
    title = title or "sample paper"
    return WorkshopKit(
        title=title,
        opening_hook=(
            f"This paper gives a {audience} something concrete to test, debate, "
            "and carry into the next session."
        ),
        slide_outline=[
            "What problem is the paper trying to solve?",
            "What did the authors actually build or test?",
            "What evidence supports the main claim?",
            "Where are the assumptions or blind spots?",
            "What would change our mind?",
            "What should we try next week?",
        ],
        discussion_questions=[
            "Which claim feels strongest, and which feels most fragile?",
            "What background knowledge does the paper assume?",
            "What would a skeptical reader ask for next?",
            "Which result is interesting enough to reproduce or extend?",
            "Where does this paper fit into the broader conversation?",
        ],
        skeptical_objections=[
            SkepticalObjection(
                objection="The evidence may not justify the strongest framing.",
                why_it_matters="A good workshop should separate what the paper proves from what it implies.",
            ),
            SkepticalObjection(
                objection="The evaluation setup may be narrower than the claims.",
                why_it_matters="If the test bed is narrow, the room should discuss how well the result travels.",
            ),
            SkepticalObjection(
                objection="Important implementation details may be underspecified.",
                why_it_matters="Missing details affect whether the group can trust or reproduce the work.",
            ),
        ],
        action_items=[
            "Pick one figure or result to reproduce locally.",
            "List the paper's strongest assumption and how to test it.",
            "Compare this paper to one adjacent baseline or prior work.",
            "Write down one question to revisit after the workshop.",
        ],
    )


def print_items(title: str, items: list[str]) -> None:
    """Print a short bullet list section."""
    if not items:
        return
    print_section(title)
    for item in items:
        print(f"- {item}")


def print_objections(objections: list[SkepticalObjection]) -> None:
    """Print skeptical objections in a compact workshop-friendly form."""
    if not objections:
        return
    print_section("Skeptical objections")
    for item in objections:
        print(f"- {item.objection}")
        print(f"  Why it matters: {item.why_it_matters}")


async def build_packet(
    source: Source,
    *,
    source_label: str,
    audience: str,
    config: Config,
    ttl: int,
    wants_cache: bool,
) -> tuple[WorkshopKit, ResultEnvelope, ResultEnvelope, str]:
    """Build the workshop packet from one paper source."""
    prompts = build_prompts(audience)
    use_cache, cache_label = should_use_cache(config, wants_cache=wants_cache)
    cache_handle: CacheHandle | None = None

    if use_cache:
        cache_handle = await create_cache([source], config=config, ttl_seconds=ttl)
        section_env = await run_many(
            [prompt for _, prompt in prompts],
            config=config,
            options=Options(cache=cache_handle),
        )
    else:
        section_env = await run_many(
            [prompt for _, prompt in prompts],
            sources=[source],
            config=config,
        )

    section_answers = [
        (label, str(answer))
        for (label, _), answer in zip(
            prompts, section_env.get("answers", []), strict=False
        )
    ]
    notes = build_notes(section_answers)

    if config.use_mock:
        packet = mock_packet(source_label=source_label, audience=audience)
        return packet, section_env, {"usage": {}}, cache_label

    final_prompt = (
        f"Build a compact workshop packet for a {audience}. "
        "Use the paper faithfully, keep the tone practical, and avoid hype.\n\n"
        "Draft notes:\n"
        f"{notes}"
    )

    if cache_handle is not None:
        packet_env = await run_many(
            [final_prompt],
            config=config,
            options=Options(cache=cache_handle, response_schema=WorkshopKit),
        )
    else:
        packet_env = await run_many(
            [final_prompt],
            sources=[
                source,
                Source.from_text(notes, identifier="draft-workshop-notes"),
            ],
            config=config,
            options=Options(response_schema=WorkshopKit),
        )

    structured = packet_env.get("structured", [])
    first = structured[0] if isinstance(structured, list) and structured else None
    packet = (
        first
        if isinstance(first, WorkshopKit)
        else fallback_packet(source_label=source_label, section_answers=section_answers)
    )
    return packet, section_env, packet_env, cache_label


async def main_async(
    source: Source,
    *,
    source_label: str,
    audience: str,
    config: Config,
    ttl: int,
    wants_cache: bool,
) -> None:
    packet, section_env, packet_env, cache_label = await build_packet(
        source,
        source_label=source_label,
        audience=audience,
        config=config,
        ttl=ttl,
        wants_cache=wants_cache,
    )
    slide_count = len(packet.slide_outline)
    question_count = len(packet.discussion_questions)
    objection_count = len(packet.skeptical_objections)
    action_count = len(packet.action_items)

    print_section("Workshop packet")
    print_kv_rows(
        [
            ("Status", packet_env.get("status", section_env.get("status", "ok"))),
            ("Source", source_label),
            ("Audience", audience),
            ("Cache", cache_label),
            ("Slides", slide_count),
            ("Questions", question_count),
            ("Objections", objection_count),
            ("Actions", action_count),
        ]
    )

    print_section("Opening hook")
    print(f"  {packet.opening_hook}")
    print_items("Slide outline", packet.slide_outline)
    print_items("Discussion questions", packet.discussion_questions)
    print_objections(packet.skeptical_objections)
    print_items("Next-week actions", packet.action_items)
    print_usage(merged_usage(section_env, packet_env))
    print_learning_hints(
        [
            "Next: swap the audience to see how the packet changes for a different room.",
            "Next: trim or reorder the slide outline before using it live.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn one paper into a workshop packet with slides, questions, objections, and actions.",
    )
    parser.add_argument(
        "--input", type=Path, default=None, help="Path to a local paper file"
    )
    parser.add_argument(
        "--arxiv",
        default=None,
        help="arXiv id or URL to analyze instead of a local file",
    )
    parser.add_argument(
        "--audience",
        default=DEFAULT_AUDIENCE,
        help="Who the packet is for (for example: reading group, seminar, journal club).",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=3600,
        help="Cache TTL in seconds when persistent caching is enabled.",
    )
    parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use persistent caching when the provider supports it.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    if args.input is not None and args.arxiv is not None:
        raise SystemExit("Choose exactly one of --input or --arxiv.")

    if args.arxiv:
        source = Source.from_arxiv(args.arxiv)
        source_label = args.arxiv
    else:
        if args.input is not None:
            path = resolve_file_or_exit(
                args.input,
                search_dir=DEFAULT_MEDIA_DEMO_DIR,
                exts=[".pdf", ".txt", ".md"],
                hint="No paper found. Run `just demo-data` or pass --input /path/to/paper.pdf.",
            )
        elif DEFAULT_PAPER_DEMO_FILE is not None:
            path = DEFAULT_PAPER_DEMO_FILE
        else:
            path = resolve_file_or_exit(
                None,
                search_dir=DEFAULT_MEDIA_DEMO_DIR,
                exts=[".pdf", ".txt", ".md"],
                hint="No paper found. Run `just demo-data` or pass --input /path/to/paper.pdf.",
            )
        if path.suffix.lower() in {".txt", ".md"}:
            source = Source.from_text(
                path.read_text(encoding="utf-8"), identifier=path.name
            )
        else:
            source = Source.from_file(path)
        source_label = str(path)

    config = build_config_or_exit(args)
    print_header("Paper-to-Workshop Kit", config=config)
    asyncio.run(
        main_async(
            source,
            source_label=source_label,
            audience=args.audience.strip() or DEFAULT_AUDIENCE,
            config=config,
            ttl=max(1, int(args.ttl)),
            wants_cache=bool(args.cache),
        )
    )


if __name__ == "__main__":
    main()
