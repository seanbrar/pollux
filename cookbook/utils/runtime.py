"""Shared runtime helpers for cookbook recipes."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from pollux import Config
from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash-lite"


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    """Add common provider/model/runtime arguments to a recipe parser."""
    parser.add_argument(
        "--provider",
        choices=("gemini", "openai"),
        default=DEFAULT_PROVIDER,
        help="Model provider to use.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model id for the selected provider.",
    )
    parser.add_argument(
        "--mock",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=("Run in mock mode (default: enabled). Use --no-mock for real API calls."),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key override. Usually read from environment.",
    )


def build_config_or_exit(args: argparse.Namespace) -> Config:
    """Build Config from parsed args, exiting with a concise actionable error."""
    try:
        return Config(
            provider=args.provider,
            model=args.model,
            use_mock=bool(args.mock),
            api_key=args.api_key,
        )
    except ConfigurationError as exc:
        hint = f" Hint: {exc.hint}" if exc.hint else ""
        print(f"Configuration error: {exc}.{hint}", file=sys.stderr)
        raise SystemExit(2) from exc


def print_run_mode(config: Config) -> None:
    """Print a compact runtime mode line for recipe users."""
    mode = "mock" if config.use_mock else "real-api"
    caching = f"on(ttl={config.ttl_seconds}s)" if config.enable_caching else "off"
    extra = ""
    # Keep the mode line compact; only call out non-default concurrency.
    if getattr(config, "request_concurrency", 6) != 6:
        extra = f" | request_concurrency={config.request_concurrency}"
    print(
        f"Mode: {mode} | provider={config.provider} | model={config.model} | caching={caching}{extra}"
    )


def usage_tokens(envelope: ResultEnvelope) -> int | None:
    """Return total token count when available in envelope usage."""
    usage = envelope.get("usage")
    if isinstance(usage, dict):
        raw = usage.get("total_token_count")
        if isinstance(raw, int):
            return raw
    return None
