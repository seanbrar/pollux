#!/usr/bin/env python3
"""🎯 Recipe: Resume Long Batch Runs and Rerun Only Failures.

When you need to: Make long-running batches resilient by persisting per-item
state and resuming only the failed work on the next run.

Ingredients:
- A list of work items (files, or (source,prompt) pairs)
- An `outputs/manifest.json` to track item status across runs

What you'll learn:
- Durable manifest pattern with per-item status and metrics
- Idempotency via `cache_override_name` to avoid duplicate work
- Safe retry with backoff and partial reruns

Difficulty: ⭐⭐⭐
Time: ~10-15 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import mimetypes
from pathlib import Path
from typing import Any

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR
from pollux import types
from pollux.frontdoor import run_batch
from pollux.types import make_execution_options

MANIFEST_PATH = Path("outputs/manifest.json")
OUTPUTS_DIR = Path("outputs/items")


@dataclass
class Item:
    id: str
    source_path: str
    prompt: str
    status: str = "pending"  # pending | ok | error
    retries: int = 0
    result_path: str | None = None
    error: str | None = None
    metrics: dict[str, Any] | None = None


def _load_manifest(path: Path) -> list[Item]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    items: list[Item] = []
    for row in data:
        items.append(Item(**row))
    return items


def _save_manifest(path: Path, items: list[Item]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(i) for i in items], indent=2))


def _is_supported_file(path: Path) -> bool:
    """Skip obvious unsupported media that require async activation (video/audio)."""
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return True
    return not mime.startswith(("video/", "audio/"))


def _default_items_from_directory(dir_path: Path, prompt: str) -> list[Item]:
    items: list[Item] = []
    for p in sorted(dir_path.rglob("*")):
        if not p.is_file():
            continue
        if not _is_supported_file(p):
            continue
        # Use filename (with extension) to avoid ID collisions like song.mp3 vs song.flac
        items.append(
            Item(
                id=p.name,
                source_path=str(p),
                prompt=prompt,
            )
        )
    return items


async def _process_item(item: Item) -> Item:
    src = types.Source.from_file(item.source_path)
    opts = make_execution_options(cache_override_name=f"resume-{item.id}")

    env = await run_batch([item.prompt], [src], prefer_json=True, options=opts)

    answers = env.get("answers", [])
    out = {
        "status": env.get("status", "ok"),
        "answer": answers[0] if answers else "",
        "metrics": env.get("metrics", {}),
        "usage": env.get("usage", {}),
        "extraction_method": env.get("extraction_method"),
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    result_path = OUTPUTS_DIR / f"{item.id}.json"
    result_path.write_text(json.dumps(out, indent=2))

    item.status = "ok" if env.get("status") == "ok" else "partial"
    item.result_path = str(result_path)
    item.metrics = env.get("metrics") or {}
    return item


async def run_resume(
    *,
    items: list[Item],
    failed_only: bool = False,
    max_retries: int = 2,
    backoff_s: float = 1.5,
) -> list[Item]:
    # Merge with existing manifest
    existing = {i.id: i for i in _load_manifest(MANIFEST_PATH)}
    merged: list[Item] = []
    for i in items:
        merged.append(existing.get(i.id, i))

    # Filter
    queue: list[Item] = (
        [i for i in merged if i.status != "ok"] if failed_only else merged
    )

    for item in queue:
        attempts = 0
        while attempts <= max_retries:
            try:
                updated = await _process_item(item)
                # Promote partial to ok if answer present
                if updated.status in ("ok", "partial"):
                    item.status = "ok" if updated.status == "ok" else updated.status
                    item.result_path = updated.result_path
                    item.metrics = updated.metrics
                    item.error = None
                    break
            except Exception as e:
                item.error = str(e)
                item.status = "error"
                item.retries += 1
                attempts += 1
                if attempts > max_retries:
                    break
                # Backoff without blocking the event loop
                await asyncio.sleep(backoff_s * attempts)
        _save_manifest(MANIFEST_PATH, merged)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume and rerun only failures")
    parser.add_argument(
        "directory", type=Path, nargs="?", help="Directory of files to process"
    )
    parser.add_argument(
        "--prompt",
        default="Summarize the key contributions in 3 bullets.",
        help="Prompt to apply",
    )
    parser.add_argument(
        "--failed-only", action="store_true", help="Only rerun failed items"
    )
    args = parser.parse_args()

    directory = args.directory or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass a directory.")

    items = _default_items_from_directory(directory, args.prompt)
    merged = asyncio.run(run_resume(items=items, failed_only=args.failed_only))

    ok = sum(1 for i in merged if i.status == "ok")
    err = sum(1 for i in merged if i.status == "error")
    print(f"✅ Completed: {ok} | ❌ Errors: {err} | Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
