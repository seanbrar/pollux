#!/usr/bin/env python3
"""Recipe: Resume long runs and retry only failed work.

Problem:
    Long runs fail partway through (network blips, provider hiccups, bad inputs)
    and you need to continue without reprocessing successful items.

Pattern:
    - Persist per-item state in a manifest.
    - Write per-item outputs to disk.
    - On rerun, process only non-"ok" items.

Run:
    python -m cookbook production/resume-on-failure --input ./my_docs
    python -m cookbook production/resume-on-failure --input ./my_docs --failed-only

Success check:
    - `outputs/manifest.json` is created and updated incrementally.
    - Re-running with `--failed-only` skips completed items.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, pick_files_by_ext
from cookbook.utils.presentation import (
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
)
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
)
from pollux import Config, Source, run

DEFAULT_MANIFEST = Path("outputs/manifest.json")
DEFAULT_OUTPUT_DIR = Path("outputs/items")


@dataclass
class WorkItem:
    """Persistent status for one source file in a resumable run."""

    id: str
    source_path: str
    prompt: str
    status: str = "pending"  # pending | ok | partial | error
    retries: int = 0
    output_path: str | None = None
    error: str | None = None
    metrics: dict[str, Any] | None = None


def make_item_id(path: Path) -> str:
    """Generate stable id from file path while avoiding collisions."""
    digest = hashlib.sha1(str(path).encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{path.stem}-{digest[:10]}"


def load_manifest(path: Path) -> list[WorkItem]:
    """Load manifest from disk if it exists."""
    if not path.exists():
        return []

    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit(f"Manifest must contain a list of items: {path}")
    return [WorkItem(**row) for row in raw]


def save_manifest(path: Path, items: list[WorkItem]) -> None:
    """Persist full manifest after each item for safe resumability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(item) for item in items], indent=2))


def build_items(directory: Path, prompt: str, limit: int) -> list[WorkItem]:
    """Build deterministic work items from files in a directory."""
    files = pick_files_by_ext(
        directory,
        [".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"],
        limit=max(1, limit),
    )
    if not files:
        raise SystemExit(f"No supported files found under: {directory}")

    return [
        WorkItem(id=make_item_id(path), source_path=str(path), prompt=prompt)
        for path in files
    ]


async def process_item(item: WorkItem, *, config: Config, output_dir: Path) -> WorkItem:
    """Execute one item and write a per-item result artifact."""
    envelope = await run(
        item.prompt, source=Source.from_file(item.source_path), config=config
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = output_dir / f"{item.id}.json"
    result_payload = {
        "source_path": item.source_path,
        "status": envelope.get("status", "ok"),
        "answers": envelope.get("answers", []),
        "usage": envelope.get("usage", {}),
        "metrics": envelope.get("metrics", {}),
    }
    result_file.write_text(json.dumps(result_payload, indent=2))

    item.status = str(envelope.get("status", "ok"))
    item.output_path = str(result_file)
    item.error = None
    item.metrics = (
        envelope.get("metrics") if isinstance(envelope.get("metrics"), dict) else {}
    )
    return item


async def run_resumable(
    *,
    items: list[WorkItem],
    config: Config,
    manifest_path: Path,
    output_dir: Path,
    failed_only: bool,
    max_retries: int,
    backoff_seconds: float,
) -> list[WorkItem]:
    """Run items with retries and durable manifest updates."""
    existing_by_id = {item.id: item for item in load_manifest(manifest_path)}
    merged: list[WorkItem] = [existing_by_id.get(item.id, item) for item in items]

    queue = [item for item in merged if item.status != "ok"] if failed_only else merged
    total = len(queue)

    for index, item in enumerate(queue, start=1):
        print(
            f"[{index}/{total}] Processing {Path(item.source_path).name} (status={item.status})"
        )
        attempts = 0
        while attempts <= max_retries:
            try:
                await process_item(item, config=config, output_dir=output_dir)
                break
            except Exception as exc:
                attempts += 1
                item.retries += 1
                item.status = "error"
                item.error = str(exc)
                if attempts > max_retries:
                    print(f"  -> failed after {attempts} attempt(s): {exc}")
                    break
                print(f"  -> retrying in {backoff_seconds * attempts:.1f}s ({exc})")
                await asyncio.sleep(backoff_seconds * attempts)
        save_manifest(manifest_path, merged)

    return merged


def summarize(items: list[WorkItem], manifest_path: Path) -> None:
    """Print end-of-run manifest summary."""
    counts = {"ok": 0, "partial": 0, "error": 0, "pending": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1

    print_section("Run summary")
    print_kv_rows(
        [
            (
                "Item status",
                "ok={ok} partial={partial} error={error} pending={pending}".format(
                    **counts
                ),
            ),
            ("Manifest", manifest_path),
        ]
    )
    print_learning_hints(
        [
            (
                "Next: rerun with `--failed-only` to verify that completed work is skipped."
                if counts.get("error", 0) == 0 and counts.get("pending", 0) == 0
                else "Next: use `--failed-only` to retry unresolved work without reprocessing successes."
            ),
            "Next: treat the manifest as the source of truth for recovery and auditing.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a resilient pipeline with persistent manifest-based resume.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_TEXT_DEMO_DIR,
        help="Directory of files to process.",
    )
    parser.add_argument(
        "--prompt",
        default="Summarize the key contributions in 3 bullets.",
        help="Prompt to apply to each file.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Maximum number of files to process.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to manifest JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for per-item result JSON files.",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Process only non-ok items from the existing manifest.",
    )
    parser.add_argument(
        "--max-retries", type=int, default=2, help="Retry count per item."
    )
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=1.5,
        help="Base backoff delay between retries.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(
            "Input directory not found. Run `just demo-data` or pass --input /path/to/dir."
        )

    config = build_config_or_exit(args)
    items = build_items(args.input, args.prompt, args.limit)

    print_header("Resumable production run", config=config)
    merged = asyncio.run(
        run_resumable(
            items=items,
            config=config,
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            failed_only=args.failed_only,
            max_retries=max(0, int(args.max_retries)),
            backoff_seconds=max(0.0, float(args.backoff_seconds)),
        )
    )
    summarize(merged, args.manifest)


if __name__ == "__main__":
    main()
