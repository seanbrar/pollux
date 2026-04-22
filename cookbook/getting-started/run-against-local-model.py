#!/usr/bin/env python3
"""Recipe: Run a prompt against a self-hosted OpenAI-compatible model.

Problem:
    You want to iterate on prompts locally for speed, privacy, or cost without
    changing pipeline code when you later swap in a cloud provider.

Key idea:
    `Config(provider="local", model=..., base_url=...)` points Pollux at a
    self-hosted server that speaks OpenAI Chat Completions. The `run()` call is
    identical to any cloud provider; only the `Config` changes.

When to use:
    - You are prototyping against a quantized model on local hardware.
    - You need to validate a pipeline on private data before sending it to a
      cloud provider.

When not to use:
    - You rely on file inputs, URLs, tool calling, reasoning controls, or
      context caching. The local provider is text-only by design; see
      docs/reference/provider-capabilities.md for the full matrix.

Run (against a real local server):
    export POLLUX_LOCAL_BASE_URL="http://localhost:11434/v1"
    python -m cookbook getting-started/run-against-local-model \\
        --no-mock --model gemma3:4b

Run (mock mode, no server needed):
    python -m cookbook getting-started/run-against-local-model

Success check:
    - Status is "ok".
    - Output includes an answer excerpt from the local model (or a mock echo
      in mock mode).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from pollux import Config, Source, run
from pollux.errors import ConfigurationError

DEFAULT_MODEL = "gemma3:4b"
DEFAULT_CONTEXT = (
    "Pollux is a Python library for multimodal orchestration on LLM APIs. "
    "It provides source patterns (fan-out, fan-in, broadcast), context "
    "caching, and an async execution pipeline."
)
DEFAULT_PROMPT = "Summarize the passage in 2 sentences."


async def main_async(context: str, prompt: str, *, config: Config) -> None:
    envelope = await run(prompt, source=Source.from_text(context), config=config)

    status = envelope.get("status", "ok")
    answers = envelope.get("answers", [])
    answer = str(answers[0]) if answers else ""

    print_section("Result")
    print_kv_rows(
        [
            ("Status", status),
            ("Provider", config.provider),
            ("Model", config.model),
            ("Base URL", config.base_url or "(mock)"),
        ]
    )
    print_excerpt("Answer excerpt", answer, limit=600)
    print_usage(envelope)

    hints = []
    if config.use_mock:
        hints.append(
            "Next: set POLLUX_LOCAL_BASE_URL (or pass --base-url) and rerun "
            "with --no-mock to hit your local server."
        )
    hints.append(
        "Next: keep the same prompt and swap Config to "
        '`Config(provider="gemini", model="gemini-2.5-flash-lite")`; the '
        "call site does not change."
    )
    if len(answer.strip()) < 80:
        hints.append(
            "Next: tighten the prompt and context if the answer is thin; "
            "local models benefit from more explicit instructions."
        )
    print_learning_hints(hints)


def build_config_or_exit(args: argparse.Namespace) -> Config:
    """Build a local Config, translating ConfigurationError into a clean exit.

    The local provider is fixed for this recipe, so we do not reuse the shared
    ``add_runtime_args`` / ``build_config_or_exit`` helpers: those expose
    ``--provider`` choices for cloud providers only. Here we surface the two
    local-specific knobs (``--base-url`` and ``--model``) directly.
    """
    try:
        return Config(
            provider="local",
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            use_mock=bool(args.mock),
        )
    except ConfigurationError as exc:
        hint = f" Hint: {exc.hint}" if exc.hint else ""
        print(f"Configuration error: {exc}.{hint}", file=sys.stderr)
        raise SystemExit(2) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a single prompt against a self-hosted OpenAI-compatible model."
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "Model identifier as exposed by the local server "
            "(for example, 'gemma3:4b' or a GGUF filename)."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "OpenAI-compatible endpoint, e.g. http://localhost:11434/v1. "
            "Falls back to POLLUX_LOCAL_BASE_URL. Not required in mock mode."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional token; most local servers ignore it.",
    )
    parser.add_argument(
        "--mock",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run in mock mode (default: enabled). Use --no-mock to hit the server.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt to run against the context.",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_CONTEXT,
        help="Plain text context to send alongside the prompt.",
    )
    args = parser.parse_args()

    config = build_config_or_exit(args)

    print_header("Local model: text-only swap-in", config=config)
    asyncio.run(main_async(args.text, args.prompt, config=config))


if __name__ == "__main__":
    main()
