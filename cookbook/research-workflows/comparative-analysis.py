#!/usr/bin/env python3
"""Recipe: Compare two sources with structured JSON output.

Problem:
    You need side-by-side similarities and differences across documents.

Pattern:
    - Request strict JSON from the model.
    - Parse defensively.
    - Print a compact decision-ready summary.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR
from cookbook.utils.json_tools import coerce_json
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
)
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
)
from pollux import Config, Source, run_many

PROMPT = (
    "Return application/json only with keys: similarities (list), differences (list), "
    "strengths (list), weaknesses (list)."
)


@dataclass
class Comparison:
    similarities: list[str]
    differences: list[str]
    strengths: list[str]
    weaknesses: list[str]


def parse_comparison(raw: str) -> Comparison | None:
    """Parse robust JSON model output into comparison object."""
    data = coerce_json(raw)
    if not isinstance(data, dict):
        return None

    def as_list(name: str) -> list[str]:
        value = data.get(name, [])
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    return Comparison(
        similarities=as_list("similarities"),
        differences=as_list("differences"),
        strengths=as_list("strengths"),
        weaknesses=as_list("weaknesses"),
    )


async def main_async(paths: list[Path], *, config: Config) -> None:
    sources = [Source.from_file(path) for path in paths]
    envelope = await run_many([PROMPT], sources=sources, config=config)

    answer = str((envelope.get("answers") or [""])[0])
    parsed = parse_comparison(answer)

    print_section("Comparative analysis")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Sources", ", ".join(str(path) for path in paths)),
        ]
    )

    if parsed is None:
        print_kv_rows([("Parse status", "Could not parse JSON output")])
        print_excerpt("Raw excerpt", answer, limit=400)
        print_learning_hints(
            [
                "Next: tighten JSON-only instructions and required keys in the prompt.",
                "Next: keep source scope narrow so comparisons stay concrete.",
            ]
        )
        return

    print_kv_rows(
        [
            (
                "Counts",
                " ".join(
                    [
                        f"similarities={len(parsed.similarities)}",
                        f"differences={len(parsed.differences)}",
                        f"strengths={len(parsed.strengths)}",
                        f"weaknesses={len(parsed.weaknesses)}",
                    ]
                ),
            ),
        ]
    )
    if parsed.differences:
        print_kv_rows([("First key difference", parsed.differences[0])])
    print_learning_hints(
        [
            "Next: constrain comparison dimensions (method, evidence, risk) if differences are weak.",
            "Next: add schema validation before using outputs in downstream systems.",
        ]
    )


def pick_paths(directory: Path, limit: int) -> list[Path]:
    """Select deterministic files from a directory up to a limit."""
    candidates = sorted(path for path in directory.rglob("*") if path.is_file())
    if len(candidates) < 2:
        raise SystemExit(f"Need at least two files under: {directory}")
    return candidates[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce a structured source-to-source comparison.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=None,
        help="Two or more input files, or a single directory to auto-pick from.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Max files to compare (default: 2)",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    inputs: list[Path] = list(args.input) if args.input else []
    if len(inputs) == 1 and inputs[0].is_dir():
        paths = pick_paths(inputs[0], args.limit)
    elif len(inputs) >= 2:
        paths = inputs
    else:
        if not DEFAULT_TEXT_DEMO_DIR.exists():
            raise SystemExit(
                "Need two files. Run `make demo-data` or provide --input with two paths."
            )
        paths = pick_paths(DEFAULT_TEXT_DEMO_DIR, args.limit)

    config = build_config_or_exit(args)
    print_header("Research comparison baseline", config=config)
    asyncio.run(main_async(paths[: args.limit], config=config))


if __name__ == "__main__":
    main()
