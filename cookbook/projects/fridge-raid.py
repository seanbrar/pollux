#!/usr/bin/env python3
"""Recipe: Turn fridge clues into a weeknight meal raid plan.

Problem:
    You have ingredients, fragments of ingredients, and a vague sense that
    something should be cooked before it turns sad. You need a plan fast.

When to use:
    - You want a small meal plan from fridge photos and pantry notes.
    - You want a project recipe that reads fridge photos and turns them into
      typed meal ideas with a shopping list.

When not to use:
    - You need strict nutrition tracking or recipe-site precision.
    - You want a shopping assistant for a full week of meal prep.

Run:
    python -m cookbook projects/fridge-raid path/to/fridge.jpg --note "eggs, rice, scallions" --no-mock

Success check:
    - Output shows a readable ingredient list with uncertainty notes.
    - Output includes meals, shopping delta, and a leftover plan.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from cookbook.utils.demo_inputs import (
    DEFAULT_FRIDGE_DEMO_FILE,
    DEFAULT_MEDIA_DEMO_DIR,
    pick_file_by_ext,
)
from cookbook.utils.presentation import (
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit, merged_usage
from pollux import Config, Options, Source, run_many

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

DEFAULT_STYLE = "weeknight comfort"


class IngredientGuess(BaseModel):
    name: str = Field(description="Ingredient name.")
    source: str = Field(
        description="Where the ingredient came from: visible, note, or both."
    )
    confidence: str = Field(description="Confidence level: high, medium, or low.")


class KitchenState(BaseModel):
    ingredients: list[IngredientGuess] = Field(
        description="Usable ingredient guesses from images and notes."
    )
    uncertain_items: list[str] = Field(
        description="Items that might be present but should be checked manually."
    )
    cooking_notes: list[str] = Field(
        description="Short notes about the kitchen state or likely constraints."
    )


class MealIdea(BaseModel):
    name: str = Field(description="Short meal name.")
    why_it_fits: str = Field(description="Why the meal fits this kitchen state.")
    use_first: list[str] = Field(description="Ingredients to prioritize first.")
    missing_items: list[str] = Field(description="Small missing items that would help.")


class FridgeRaidPlan(BaseModel):
    headline: str = Field(description="Short title for the raid plan.")
    meals: list[MealIdea] = Field(description="2-4 meal ideas.")
    shopping_delta: list[str] = Field(description="Small shopping top-up list.")
    leftover_plan: list[str] = Field(description="What to reuse later.")
    waste_watch: list[str] = Field(
        description="Items most likely to be forgotten or wasted."
    )


def resolve_image_inputs(user_images: list[str]) -> list[Path]:
    """Resolve explicit image paths or fall back to the bundled sample image."""
    if user_images:
        paths = [Path(raw) for raw in user_images]
        missing = [path for path in paths if not path.exists()]
        if missing:
            raise SystemExit(f"Image not found: {missing[0]}")
        return paths

    fallback = DEFAULT_FRIDGE_DEMO_FILE or pick_file_by_ext(
        DEFAULT_MEDIA_DEMO_DIR, [".jpg", ".jpeg", ".png"]
    )
    if fallback is None:
        raise SystemExit(
            "No sample fridge image found. Run `just demo-data` or pass one or more image paths."
        )
    return [fallback]


def parse_pantry_note(note: str) -> list[str]:
    """Split a pantry note into clean ingredient hints."""
    if not note.strip():
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in re.split(r"[\n,;/]+", note):
        cleaned = raw.strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            items.append(cleaned)
    return items


def build_sources(image_paths: list[Path], pantry_note: str) -> list[Source]:
    """Build the multimodal source list for the inventory pass."""
    sources = [Source.from_file(path) for path in image_paths]
    note_items = parse_pantry_note(pantry_note)
    if note_items:
        sources.append(
            Source.from_text(
                "Pantry note: " + ", ".join(note_items),
                identifier="pantry-note",
            )
        )
    return sources


def build_inventory_prompt(style: str) -> str:
    """Return the inventory-extraction prompt."""
    return (
        f"You are raiding the fridge for a {style} meal. "
        "Extract a compact kitchen state from the images and pantry note. "
        "List ingredients that look usable, flag anything you're not sure about, "
        "and note what needs to be used before it turns sad."
    )


def build_plan_prompt(style: str, max_meals: int) -> str:
    """Return the final planning prompt."""
    return (
        f"Raid the fridge: turn this kitchen state into a {style} plan with {max_meals} meals or fewer. "
        "Keep meals realistic for a weeknight, skip unnecessary shopping, "
        "and plan leftovers on purpose — no forgetting things in the back."
    )


def mock_kitchen_state(*, pantry_note: str, image_paths: list[Path]) -> KitchenState:
    """Return a credible kitchen state for mock mode and fallbacks."""
    ingredients: list[IngredientGuess] = []
    note_items = parse_pantry_note(pantry_note)
    for item in note_items:
        ingredients.append(IngredientGuess(name=item, source="note", confidence="high"))

    if image_paths:
        visible_defaults = ["greens", "milk", "a half-used sauce jar"]
        for item in visible_defaults:
            if item not in {entry.name for entry in ingredients}:
                ingredients.append(
                    IngredientGuess(name=item, source="visible", confidence="medium")
                )

    return KitchenState(
        # Fallback when both note and image lists are empty.
        ingredients=ingredients
        or [
            IngredientGuess(name="eggs", source="visible", confidence="medium"),
            IngredientGuess(name="greens", source="visible", confidence="medium"),
        ],
        uncertain_items=["Check freshness on anything leafy or already opened."],
        cooking_notes=[
            "The goal is to use what already exists before buying much more.",
        ],
    )


def fallback_plan(kitchen_state: KitchenState, *, style: str) -> FridgeRaidPlan:
    """Return a structurally complete plan when structured output is unavailable."""
    names = [i.name for i in kitchen_state.ingredients[:4]]
    return FridgeRaidPlan(
        headline=f"{style.title()} fridge raid",
        meals=[
            MealIdea(
                name="Odds-and-Ends Skillet",
                why_it_fits="Uses what's already there without extra shopping.",
                use_first=names[:2] or ["whatever looks freshest"],
                missing_items=["one good all-purpose seasoning"],
            ),
            MealIdea(
                name="Soup or Noodles Night",
                why_it_fits="A low-drama fallback that keeps the plan honest.",
                use_first=names[2:4] or ["greens or roots"],
                missing_items=["broth or noodles"],
            ),
        ],
        shopping_delta=["Nothing urgent. Top up only if you want range."],
        leftover_plan=["Cook once, reuse the base for lunch or a second dinner."],
        waste_watch=kitchen_state.uncertain_items
        or [
            "Check nearly empty jars and dairy before they vanish into fridge folklore."
        ],
    )


def print_ingredients(kitchen_state: KitchenState) -> None:
    """Print the normalized ingredient view."""
    print_section("Kitchen state")
    for ingredient in kitchen_state.ingredients:
        print(
            f"- {ingredient.name}: source={ingredient.source} | confidence={ingredient.confidence}"
        )
    if kitchen_state.uncertain_items:
        print_section("Check before cooking")
        for uncertain_item in kitchen_state.uncertain_items:
            print(f"- {uncertain_item}")


def print_plan(plan: FridgeRaidPlan) -> None:
    """Print the final raid plan."""
    print_section("Raid plan")
    print(f"  {plan.headline}")

    print_section("Meals")
    for meal in plan.meals:
        print(f"- {meal.name}")
        print(f"  Why it fits: {meal.why_it_fits}")
        print(f"  Use first: {', '.join(meal.use_first) or 'nothing urgent'}")
        print(f"  Missing items: {', '.join(meal.missing_items) or 'none'}")

    print_section("Shopping delta")
    for item in plan.shopping_delta:
        print(f"- {item}")

    print_section("Leftover plan")
    for item in plan.leftover_plan:
        print(f"- {item}")

    print_section("Waste watch")
    for item in plan.waste_watch:
        print(f"- {item}")


async def run_mock_flow(
    sources: list[Source],
    *,
    image_paths: list[Path],
    pantry_note: str,
    style: str,
    config: Config,
) -> tuple[KitchenState, FridgeRaidPlan, ResultEnvelope]:
    """Exercise one Pollux call, then render a deterministic mock artifact."""
    envelope = await run_many(
        [build_inventory_prompt(style)],
        sources=sources,
        config=config,
    )
    kitchen_state = mock_kitchen_state(pantry_note=pantry_note, image_paths=image_paths)
    plan = fallback_plan(kitchen_state, style=style)
    return kitchen_state, plan, envelope


async def run_real_flow(
    sources: list[Source],
    *,
    pantry_note: str,
    image_paths: list[Path],
    style: str,
    max_meals: int,
    config: Config,
) -> tuple[KitchenState, FridgeRaidPlan, ResultEnvelope]:
    """Run the two-pass multimodal workflow."""
    inventory_env = await run_many(
        [build_inventory_prompt(style)],
        sources=sources,
        config=config,
        options=Options(response_schema=KitchenState),
    )
    structured_state = inventory_env.get("structured", [])
    first_state = structured_state[0] if structured_state else None
    kitchen_state = (
        first_state
        if isinstance(first_state, KitchenState)
        else mock_kitchen_state(pantry_note=pantry_note, image_paths=image_paths)
    )

    plan_env = await run_many(
        [build_plan_prompt(style, max_meals)],
        sources=[Source.from_json(kitchen_state, identifier="kitchen-state")],
        config=config,
        options=Options(response_schema=FridgeRaidPlan),
    )
    structured_plan = plan_env.get("structured", [])
    first_plan = structured_plan[0] if structured_plan else None
    plan = (
        first_plan
        if isinstance(first_plan, FridgeRaidPlan)
        else fallback_plan(kitchen_state, style=style)
    )
    return kitchen_state, plan, merged_usage(inventory_env, plan_env)


async def main_async(
    image_paths: list[Path],
    *,
    pantry_note: str,
    style: str,
    max_meals: int,
    config: Config,
) -> None:
    sources = build_sources(image_paths, pantry_note)
    if config.use_mock:
        kitchen_state, plan, envelope = await run_mock_flow(
            sources,
            image_paths=image_paths,
            pantry_note=pantry_note,
            style=style,
            config=config,
        )
    else:
        kitchen_state, plan, envelope = await run_real_flow(
            sources,
            pantry_note=pantry_note,
            image_paths=image_paths,
            style=style,
            max_meals=max_meals,
            config=config,
        )

    print_section("Raid snapshot")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Images", len(image_paths)),
            ("Pantry note items", len(parse_pantry_note(pantry_note))),
            ("Meal count", len(plan.meals)),
            ("Style", style),
        ]
    )
    print_ingredients(kitchen_state)
    print_plan(plan)
    print_usage(envelope)
    print_learning_hints(
        [
            "Notice: pass 1's KitchenState becomes pass 2's Source via Source.from_json(). Try adding a field to the schema and watch it flow through.",
            "Next: swap the style to something like 'pantry pasta' or 'lazy soup night' and compare how the plan changes.",
            "Next: tighten the pantry note if the ingredient list feels too vague.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn fridge images and pantry notes into a small meal plan.",
    )
    parser.add_argument(
        "images",
        nargs="*",
        help="Zero or more kitchen image paths. If omitted, the bundled sample image is used.",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional pantry note, for example: 'eggs, rice, scallions, yogurt'.",
    )
    parser.add_argument(
        "--style",
        default=DEFAULT_STYLE,
        help="Meal-planning vibe, for example 'weeknight comfort' or 'pantry pasta night'.",
    )
    parser.add_argument(
        "--max-meals",
        type=int,
        default=3,
        help="Maximum number of meals to include in the raid plan.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    image_paths = resolve_image_inputs(args.images)
    config = build_config_or_exit(args)

    print_header("Fridge Raid", config=config)
    asyncio.run(
        main_async(
            image_paths,
            pantry_note=args.note,
            style=args.style.strip() or DEFAULT_STYLE,
            max_meals=max(1, int(args.max_meals)),
            config=config,
        )
    )


if __name__ == "__main__":
    main()
