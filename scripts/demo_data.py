#!/usr/bin/env python3
"""Install cookbook data packs from the pollux-cookbook-data repository.

Examples:
  python scripts/demo_data.py
  python scripts/demo_data.py --project spellbook-sidekick
  python scripts/demo_data.py --source ../pollux-cookbook-data
  python scripts/demo_data.py --clean
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cookbook.utils.data_packs import (  # noqa: E402
    DATA_REPO_URL,
    ENV_DATA_SOURCE,
    SHARED_PACK,
    PackSpec,
    cookbook_data_dir,
    install_pack,
    remove_installed_data,
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for cookbook pack installation."""
    parser = argparse.ArgumentParser(
        description="Install or sync cookbook data packs.",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Project pack id to install in addition to the shared pack.",
    )
    parser.add_argument(
        "--no-shared",
        action="store_false",
        dest="shared",
        default=True,
        help="Skip installing the shared starter pack.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Optional local pollux-cookbook-data checkout. "
            f"Overrides {ENV_DATA_SOURCE}."
        ),
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Optional install directory override.",
    )
    parser.add_argument(
        "--skip-fetch-assets",
        action="store_true",
        help="Skip large assets listed in fetch.toml (for example demo videos).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any optional fetched asset fails to download.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove installed cookbook data and exit.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity.",
    )
    parser.add_argument(
        "--no-pretty",
        action="store_false",
        dest="pretty",
        default=True,
        help="Disable pretty output symbols.",
    )
    return parser.parse_args()


def main() -> int:
    """Install the requested cookbook data packs."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )

    dest_base = args.dest or cookbook_data_dir()
    if args.clean:
        removed = remove_installed_data(dest_base=dest_base)
        logging.info(
            "%s removed cookbook data at %s", "✅" if args.pretty else "", removed
        )
        return 0

    specs: list[PackSpec] = []
    if args.shared:
        specs.append(SHARED_PACK)
    specs.extend(
        PackSpec(namespace="projects", pack_id=pack_id) for pack_id in args.project
    )

    if not specs:
        logging.error(
            "Nothing to install. Choose the shared pack or pass at least one --project."
        )
        return 2

    logging.info("installing cookbook data into %s", dest_base)
    if args.source is None:
        logging.info(
            "source preference: %s, then local checkout if present, then %s",
            ENV_DATA_SOURCE,
            DATA_REPO_URL,
        )

    failures_seen = False
    for spec in specs:
        label = spec.pack_id if spec.namespace == "projects" else "shared"
        installed_root, failures = install_pack(
            spec,
            dest_base=dest_base,
            source_root=args.source,
            fetch_assets=not args.skip_fetch_assets,
        )
        logging.info(
            "%s installed %s pack at %s",
            "✅" if args.pretty else "",
            label,
            installed_root,
        )
        if failures:
            failures_seen = True
            logging.warning(
                "some optional assets for %s failed to download: %s",
                label,
                ", ".join(failures),
            )

    if failures_seen and args.strict:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
