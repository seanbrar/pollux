#!/usr/bin/env python3
"""🎯 Recipe: Extract a Normalized Fact Table from Many Papers.

When you need to: Turn a directory of papers into a structured JSONL/CSV table
of findings (dataset, metric, value, method, notes) for downstream analysis.

Ingredients:
- Directory of PDFs/txt files (best with text-extracted content)
- A schema for normalized rows

What you'll learn:
- Schema-first extraction using Pydantic
- Robust JSON parsing from LLM answers with fallbacks
- Writing JSONL/CSV outputs and basic error accounting

Difficulty: ⭐⭐⭐
Time: ~12-15 minutes
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR
from pollux import types
from pollux.frontdoor import run_batch

if TYPE_CHECKING:
    from collections.abc import Iterable


class Finding(BaseModel):
    paper_title: str
    dataset: str
    metric: str
    value: str
    method: str
    notes: str


PROMPT = (
    "Extract 1-3 key quantitative findings as JSON array of objects with keys: "
    "paper_title, dataset, metric, value, method, notes. Be precise and concise."
)


def _iter_files(directory: Path) -> Iterable[Path]:
    """Yield only likely document files (txt/pdf), skip media like audio/video/images."""
    for p in sorted(directory.rglob("*")):
        if not p.is_file():
            continue
        mime, _ = mimetypes.guess_type(str(p))
        if mime and (mime.startswith(("audio/", "video/", "image/"))):
            continue
        # Accept PDFs and text-like files; other application/* types are skipped by default
        if mime == "application/pdf" or (mime and mime.startswith("text/")):
            yield p


def _try_parse_findings(answer: str) -> list[Finding]:
    # Best-effort JSON extraction
    try:
        data = json.loads(answer)
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            out: list[Finding] = []
            for row in data:
                if isinstance(row, dict):
                    out.append(Finding(**row))
            return out
    except Exception:
        return []
    return []


async def extract_one(
    path: Path,
) -> tuple[list[Finding], dict[str, Any] | None, str | None]:
    src = types.Source.from_file(path)
    env = await run_batch([PROMPT], [src], prefer_json=True)
    answers = env.get("answers", [])
    answer = str(answers[0]) if answers else ""
    finds = _try_parse_findings(answer)
    if finds:
        return finds, env.get("metrics"), None
    # Fallback: construct a minimal finding
    return (
        [
            Finding(
                paper_title=path.stem,
                dataset="",
                metric="",
                value=answer[:120],
                method="",
                notes="fallback_parse",
            )
        ],
        env.get("metrics"),
        None,
    )


async def main_async(directory: Path, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    jsonl_path = outdir / "facts.jsonl"
    csv_path = outdir / "facts.csv"

    rows: list[Finding] = []
    errors: list[str] = []
    for p in _iter_files(directory):
        try:
            fnds, _metrics, _err = await extract_one(p)
            rows.extend(fnds)
        except Exception as e:
            errors.append(f"{p.name}: {e}")

    # Write JSONL
    with jsonl_path.open("w") as f:
        for r in rows:
            f.write(r.model_dump_json())
            f.write("\n")

    # Write CSV
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "paper_title",
                "dataset",
                "metric",
                "value",
                "method",
                "notes",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r.model_dump())

    print(f"✅ Wrote {len(rows)} rows to {jsonl_path} and {csv_path}")
    if errors:
        print(f"⚠️  {len(errors)} files had errors; see logs above.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract fact table from papers")
    parser.add_argument("directory", type=Path, nargs="?", help="Directory with papers")
    parser.add_argument("--outdir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    directory = args.directory or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass a directory.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, args.outdir))


if __name__ == "__main__":
    main()
