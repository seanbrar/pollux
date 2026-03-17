#!/usr/bin/env python3
"""Probe Pollux deferred delivery with low-cost live and validation cases.

Examples:
  uv run python scripts/deferred_delivery_probe.py
  uv run python scripts/deferred_delivery_probe.py --provider openai --provider gemini
  uv run python scripts/deferred_delivery_probe.py --case single_text_roundtrip
  uv run python scripts/deferred_delivery_probe.py --case unsupported_provider_rejected
  uv run python scripts/deferred_delivery_probe.py --model openai=gpt-5-nano
  uv run python scripts/deferred_delivery_probe.py --live-only --strict
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Literal
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel

import pollux
from pollux import Config, DeferredHandle, Options, Source
from pollux.cache import CacheHandle
from pollux.errors import ConfigurationError, DeferredNotReadyError, PolluxError

ProviderName = Literal["gemini", "openai", "anthropic", "openrouter"]
CaseKind = Literal["live", "validation"]

DEFAULT_MODELS: dict[ProviderName, str] = {
    "gemini": "gemini-2.5-flash-lite-preview-09-2025",
    "openai": "gpt-5-nano",
    "anthropic": "claude-haiku-4-5",
    "openrouter": "openai/gpt-5-nano",
}
LIVE_PROVIDERS: tuple[ProviderName, ...] = ("gemini", "openai", "anthropic")
ENV_VARS: dict[ProviderName, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
CASE_DESCRIPTIONS: dict[str, tuple[CaseKind, str]] = {
    "single_text_roundtrip": (
        "live",
        "Submit one prompt, serialize/restore the handle, inspect, and collect.",
    ),
    "multi_prompt_order": (
        "live",
        "Submit three prompts and verify collection order and deferred metadata.",
    ),
    "structured_roundtrip": (
        "live",
        "Submit with response_schema, reject a mismatched schema, then collect as Pydantic.",
    ),
    "structured_plain_dicts": (
        "live",
        "Submit with response_schema and collect without a schema to get plain dicts.",
    ),
    "source_only_text": (
        "live",
        "Submit a source-only deferred job with no prompt to exercise the prompt-less path.",
    ),
    "local_text_file": (
        "live",
        "Submit a tiny local text file source to exercise deferred file uploads.",
    ),
    "cancel_fast": (
        "live",
        "Submit multi-prompt work, cancel quickly, and inspect the terminal outcome.",
    ),
    "empty_prompts_rejected": (
        "validation",
        "Verify defer_many([]) fails fast with the documented ConfigurationError.",
    ),
    "legacy_delivery_mode_rejected": (
        "validation",
        "Verify Options(delivery_mode='deferred') is rejected on defer entry points.",
    ),
    "out_of_scope_options_rejected": (
        "validation",
        "Verify deferred rejects cache, conversation continuity, tools, and implicit caching.",
    ),
    "unsupported_provider_rejected": (
        "validation",
        "Verify openrouter fails fast because deferred delivery is unsupported.",
    ),
}
DEFAULT_CASES: tuple[str, ...] = tuple(CASE_DESCRIPTIONS)


@dataclass(frozen=True, slots=True)
class RunContext:
    """Shared probe settings."""

    run_id: str
    output_path: Path
    artifact_root: Path
    poll_interval_seconds: float
    terminal_timeout_seconds: float
    keep_jobs: bool
    model_overrides: dict[ProviderName, str]


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        action="append",
        choices=LIVE_PROVIDERS,
        default=[],
        help="Provider to probe live. Repeatable. Defaults to all with configured API keys.",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="PROVIDER=MODEL",
        help="Override a default model, for example --model openai=gpt-4.1-nano.",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=sorted(CASE_DESCRIPTIONS),
        default=[],
        help="Probe case to run. Repeatable. Defaults to the full live+validation matrix.",
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Run only live provider cases.",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="Run only local validation cases.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=3.0,
        help="Seconds between inspect_deferred() polls.",
    )
    parser.add_argument(
        "--terminal-timeout-seconds",
        type=float,
        default=180.0,
        help="Maximum seconds to wait for a job to reach a terminal state.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="JSONL output path. Defaults to artifacts/deferred-probe-<timestamp>.jsonl.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Artifact directory. Defaults to artifacts/deferred-probe-<timestamp>/.",
    )
    parser.add_argument(
        "--keep-jobs",
        action="store_true",
        help="Do not auto-cancel jobs that time out before reaching a terminal state.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any case fails.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available probe cases and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the probe script."""
    args = parse_args(argv)
    if args.list_cases:
        for slug, (kind, description) in CASE_DESCRIPTIONS.items():
            print(f"{slug:<30} [{kind}] {description}", flush=True)
        return 0
    if args.live_only and args.validation_only:
        print(
            "--live-only and --validation-only are mutually exclusive.", file=sys.stderr
        )
        return 2

    load_dotenv()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.out or Path("artifacts") / f"deferred-probe-{timestamp}.jsonl"
    artifact_root = (
        args.artifact_dir or Path("artifacts") / f"deferred-probe-{timestamp}"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)

    selected_cases = _resolve_cases(args)
    model_overrides = _parse_model_overrides(args.model)
    live_providers = _resolve_live_providers(args.provider, selected_cases)

    context = RunContext(
        run_id=uuid4().hex,
        output_path=output_path,
        artifact_root=artifact_root,
        poll_interval_seconds=args.poll_interval_seconds,
        terminal_timeout_seconds=args.terminal_timeout_seconds,
        keep_jobs=bool(args.keep_jobs),
        model_overrides=model_overrides,
    )

    records = asyncio.run(run_probe(context, selected_cases, live_providers))
    print(f"Wrote {len(records)} records to {output_path}", flush=True)
    print_summary(records)

    if args.strict and any(not bool(record.get("ok")) for record in records):
        return 1
    return 0


async def run_probe(
    context: RunContext,
    selected_cases: list[str],
    live_providers: list[ProviderName],
) -> list[dict[str, Any]]:
    """Run the selected cases and persist JSONL records."""
    records: list[dict[str, Any]] = []

    with context.output_path.open("a", encoding="utf-8") as sink:
        for provider in live_providers:
            model = context.model_overrides.get(provider, DEFAULT_MODELS[provider])
            for case_name in selected_cases:
                if CASE_DESCRIPTIONS[case_name][0] != "live":
                    continue
                record = await execute_live_case(
                    context=context,
                    provider=provider,
                    model=model,
                    case_name=case_name,
                )
                records.append(record)
                sink.write(
                    json.dumps(record, sort_keys=True, default=_json_default) + "\n"
                )
                sink.flush()
                _print_record(record)

        for case_name in selected_cases:
            if CASE_DESCRIPTIONS[case_name][0] != "validation":
                continue
            record = await execute_validation_case(context=context, case_name=case_name)
            records.append(record)
            sink.write(json.dumps(record, sort_keys=True, default=_json_default) + "\n")
            sink.flush()
            _print_record(record)

    return records


async def execute_live_case(
    *,
    context: RunContext,
    provider: ProviderName,
    model: str,
    case_name: str,
) -> dict[str, Any]:
    """Execute one live provider probe case."""
    started_at = time.time()
    case_dir = context.artifact_root / provider / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    config = Config(provider=provider, model=model)

    try:
        if case_name == "single_text_roundtrip":
            details = await _case_single_text_roundtrip(context, case_dir, config)
        elif case_name == "multi_prompt_order":
            details = await _case_multi_prompt_order(context, case_dir, config)
        elif case_name == "structured_roundtrip":
            details = await _case_structured_roundtrip(context, case_dir, config)
        elif case_name == "structured_plain_dicts":
            details = await _case_structured_plain_dicts(context, case_dir, config)
        elif case_name == "source_only_text":
            details = await _case_source_only_text(context, case_dir, config)
        elif case_name == "local_text_file":
            details = await _case_local_text_file(context, case_dir, config)
        elif case_name == "cancel_fast":
            details = await _case_cancel_fast(context, case_dir, config)
        else:
            raise AssertionError(f"Unhandled live case: {case_name}")
        ok = True
        error: dict[str, Any] | None = None
    except Exception as exc:
        details = {}
        ok = False
        error = _serialize_exception(exc)
        _write_json(case_dir / "error.json", error)

    return {
        "artifact_dir": str(case_dir),
        "case": case_name,
        "description": CASE_DESCRIPTIONS[case_name][1],
        "duration_s": round(time.time() - started_at, 3),
        "kind": "live",
        "model": model,
        "ok": ok,
        "provider": provider,
        "started_at": started_at,
        "run_id": context.run_id,
        "error": error,
        **details,
    }


async def execute_validation_case(
    *,
    context: RunContext,
    case_name: str,
) -> dict[str, Any]:
    """Execute one local validation case."""
    started_at = time.time()
    case_dir = context.artifact_root / "validation" / case_name
    case_dir.mkdir(parents=True, exist_ok=True)

    try:
        if case_name == "empty_prompts_rejected":
            details = await _validation_empty_prompts_rejected(case_dir)
        elif case_name == "legacy_delivery_mode_rejected":
            details = await _validation_legacy_delivery_mode_rejected(case_dir)
        elif case_name == "out_of_scope_options_rejected":
            details = await _validation_out_of_scope_options_rejected(case_dir)
        elif case_name == "unsupported_provider_rejected":
            details = await _validation_unsupported_provider_rejected(case_dir)
        else:
            raise AssertionError(f"Unhandled validation case: {case_name}")
        ok = True
        error: dict[str, Any] | None = None
    except Exception as exc:
        details = {}
        ok = False
        error = _serialize_exception(exc)
        _write_json(case_dir / "error.json", error)

    return {
        "artifact_dir": str(case_dir),
        "case": case_name,
        "description": CASE_DESCRIPTIONS[case_name][1],
        "duration_s": round(time.time() - started_at, 3),
        "kind": "validation",
        "model": None,
        "ok": ok,
        "provider": None,
        "started_at": started_at,
        "run_id": context.run_id,
        "error": error,
        **details,
    }


async def _case_single_text_roundtrip(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    token = f"{config.provider.upper()}_DEFERRED_SINGLE_OK"
    handle = await pollux.defer(
        f"Reply with exactly {token}.",
        config=config,
    )
    return await _collect_text_case(
        context=context,
        case_dir=case_dir,
        handle=handle,
        expected_tokens=[token],
        expect_not_ready=True,
    )


async def _case_multi_prompt_order(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    tokens = [
        f"{config.provider.upper()}_ORDER_ALPHA",
        f"{config.provider.upper()}_ORDER_BRAVO",
        f"{config.provider.upper()}_ORDER_CHARLIE",
    ]
    handle = await pollux.defer_many(
        [f"Reply with exactly {token}." for token in tokens],
        config=config,
    )
    details = await _collect_text_case(
        context=context,
        case_dir=case_dir,
        handle=handle,
        expected_tokens=tokens,
        expect_not_ready=False,
    )
    diagnostics = details["result"]["diagnostics"]["deferred"]["items"]
    request_ids = [item["request_id"] for item in diagnostics]
    _ensure(
        condition=request_ids == ["pollux-000000", "pollux-000001", "pollux-000002"],
        message=f"unexpected request ids: {request_ids}",
    )
    details["request_ids"] = request_ids
    return details


async def _case_structured_roundtrip(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    class StructuredPayload(BaseModel):
        label: str
        count: int

    class WrongPayload(BaseModel):
        name: str

    handle = await pollux.defer(
        "Return JSON with label exactly 'STRUCTURED_ROUNDTRIP_OK' and count exactly 7.",
        config=config,
        options=Options(response_schema=StructuredPayload),
    )
    _write_json(case_dir / "handle.json", handle.to_dict())

    mismatch_message: str | None = None
    try:
        await pollux.collect_deferred(handle, response_schema=WrongPayload)
    except ConfigurationError as exc:
        mismatch_message = str(exc)
    _ensure(
        condition=(
            mismatch_message is not None and "does not match" in mismatch_message
        ),
        message="mismatched collect-time schema did not fail as expected",
    )

    terminal_snapshot, snapshots = await _wait_for_terminal(context, handle)
    _write_json(
        case_dir / "snapshots.json", [asdict(snapshot) for snapshot in snapshots]
    )
    _write_json(case_dir / "final_snapshot.json", asdict(terminal_snapshot))

    result = await pollux.collect_deferred(handle, response_schema=StructuredPayload)
    _write_json(case_dir / "result.json", result)

    structured = result.get("structured")
    _ensure(
        condition=isinstance(structured, list) and len(structured) == 1,
        message="missing structured output",
    )
    payload = structured[0]
    _ensure(
        condition=isinstance(payload, StructuredPayload),
        message="structured payload is not a Pydantic model",
    )
    _ensure(
        condition=payload.label == "STRUCTURED_ROUNDTRIP_OK",
        message=f"unexpected label: {payload.label!r}",
    )
    _ensure(
        condition=payload.count == 7, message=f"unexpected count: {payload.count!r}"
    )
    _ensure(
        condition=result["metrics"]["deferred"] is True,
        message="missing deferred metric flag",
    )

    return {
        "handle": handle.to_dict(),
        "schema_mismatch_error": mismatch_message,
        "terminal_snapshot": asdict(terminal_snapshot),
        "result": result,
    }


async def _case_structured_plain_dicts(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    class StructuredPayload(BaseModel):
        label: str
        enabled: bool

    handle = await pollux.defer(
        "Return JSON with label exactly 'STRUCTURED_DICT_OK' and enabled exactly true.",
        config=config,
        options=Options(response_schema=StructuredPayload),
    )
    _write_json(case_dir / "handle.json", handle.to_dict())

    terminal_snapshot, snapshots = await _wait_for_terminal(context, handle)
    _write_json(
        case_dir / "snapshots.json", [asdict(snapshot) for snapshot in snapshots]
    )
    _write_json(case_dir / "final_snapshot.json", asdict(terminal_snapshot))

    result = await pollux.collect_deferred(handle)
    _write_json(case_dir / "result.json", result)

    structured = result.get("structured")
    _ensure(
        condition=isinstance(structured, list) and len(structured) == 1,
        message="missing structured output",
    )
    payload = structured[0]
    _ensure(
        condition=isinstance(payload, dict),
        message="collect without schema should return plain dicts",
    )
    _ensure(
        condition=payload.get("label") == "STRUCTURED_DICT_OK",
        message=f"unexpected label: {payload!r}",
    )
    _ensure(
        condition=payload.get("enabled") is True,
        message=f"unexpected payload: {payload!r}",
    )

    return {
        "handle": handle.to_dict(),
        "terminal_snapshot": asdict(terminal_snapshot),
        "result": result,
    }


async def _case_source_only_text(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    token = f"{config.provider.upper()}_SOURCE_ONLY_OK"
    source = Source.from_text(
        f"Reply with exactly {token}. Do not add anything else.",
        identifier="source-only-instruction",
    )
    handle = await pollux.defer(
        prompt=None,
        source=source,
        config=config,
    )
    return await _collect_text_case(
        context=context,
        case_dir=case_dir,
        handle=handle,
        expected_tokens=[token],
        expect_not_ready=False,
    )


async def _case_local_text_file(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    token = f"{config.provider.upper()}_FILE_OK"
    input_path = case_dir / "source.txt"
    input_path.write_text(
        f"Document token: {token}\nReturn this token when asked.\n",
        encoding="utf-8",
    )
    handle = await pollux.defer(
        "Read the local file source and reply with exactly the document token.",
        source=Source.from_file(input_path),
        config=config,
    )
    details = await _collect_text_case(
        context=context,
        case_dir=case_dir,
        handle=handle,
        expected_tokens=[token],
        expect_not_ready=False,
    )
    details["input_path"] = str(input_path)
    return details


async def _case_cancel_fast(
    context: RunContext,
    case_dir: Path,
    config: Config,
) -> dict[str, Any]:
    prompts = [
        "Reply with exactly CANCEL_FAST_ONE.",
        "Reply with exactly CANCEL_FAST_TWO.",
    ]
    handle = await pollux.defer_many(prompts, config=config)
    _write_json(case_dir / "handle.json", handle.to_dict())
    await pollux.cancel_deferred(handle)

    terminal_snapshot, snapshots = await _wait_for_terminal(context, handle)
    _write_json(
        case_dir / "snapshots.json", [asdict(snapshot) for snapshot in snapshots]
    )
    _write_json(case_dir / "final_snapshot.json", asdict(terminal_snapshot))

    _ensure(
        condition=terminal_snapshot.status
        in {"cancelled", "partial", "completed", "failed", "expired"},
        message=f"unexpected cancel terminal status: {terminal_snapshot.status}",
    )
    result = await pollux.collect_deferred(handle)
    _write_json(case_dir / "result.json", result)
    _ensure(
        condition=result["metrics"]["deferred"] is True,
        message="missing deferred metric flag",
    )

    return {
        "handle": handle.to_dict(),
        "terminal_snapshot": asdict(terminal_snapshot),
        "result": result,
    }


async def _collect_text_case(
    *,
    context: RunContext,
    case_dir: Path,
    handle: DeferredHandle,
    expected_tokens: list[str],
    expect_not_ready: bool,
) -> dict[str, Any]:
    _write_json(case_dir / "handle.json", handle.to_dict())
    restored = DeferredHandle.from_dict(handle.to_dict())

    first_snapshot = await pollux.inspect_deferred(restored)
    snapshots = [first_snapshot]
    _write_json(case_dir / "initial_snapshot.json", asdict(first_snapshot))

    not_ready_observed = False
    if expect_not_ready and not first_snapshot.is_terminal:
        try:
            await pollux.collect_deferred(restored)
        except DeferredNotReadyError as exc:
            not_ready_observed = True
            _write_json(case_dir / "not_ready_snapshot.json", asdict(exc.snapshot))

    terminal_snapshot, later_snapshots = await _wait_for_terminal(
        context,
        restored,
        initial_snapshots=snapshots,
    )
    _write_json(
        case_dir / "snapshots.json", [asdict(snapshot) for snapshot in later_snapshots]
    )
    _write_json(case_dir / "final_snapshot.json", asdict(terminal_snapshot))

    result = await pollux.collect_deferred(restored)
    _write_json(case_dir / "result.json", result)

    answers = result["answers"]
    _ensure(
        condition=len(answers) == len(expected_tokens),
        message="answer count does not match prompt count",
    )
    for idx, token in enumerate(expected_tokens):
        answer = answers[idx]
        _ensure(condition=bool(answer.strip()), message=f"answer {idx} is empty")
        _ensure(
            condition=token.lower() in answer.lower(),
            message=f"answer {idx} did not include expected token {token!r}: {answer!r}",
        )

    _ensure(
        condition=result["metrics"]["deferred"] is True,
        message="missing deferred metric flag",
    )
    _ensure(
        condition=result["diagnostics"]["deferred"]["job_id"] == restored.job_id,
        message="deferred diagnostics job id did not round-trip",
    )

    return {
        "handle": restored.to_dict(),
        "immediate_not_ready_observed": not_ready_observed,
        "terminal_snapshot": asdict(terminal_snapshot),
        "result": result,
    }


async def _wait_for_terminal(
    context: RunContext,
    handle: DeferredHandle,
    *,
    initial_snapshots: list[pollux.DeferredSnapshot] | None = None,
) -> tuple[pollux.DeferredSnapshot, list[pollux.DeferredSnapshot]]:
    """Poll inspect_deferred() until the job is terminal or times out."""
    snapshots = list(initial_snapshots or [])
    if snapshots and snapshots[-1].is_terminal:
        return snapshots[-1], snapshots

    deadline = time.monotonic() + context.terminal_timeout_seconds
    last_snapshot = snapshots[-1] if snapshots else None

    while True:
        if time.monotonic() >= deadline:
            if not context.keep_jobs:
                with suppress(Exception):
                    await pollux.cancel_deferred(handle)
            raise TimeoutError(
                f"job {handle.job_id} did not reach a terminal state within "
                f"{context.terminal_timeout_seconds}s"
            )

        snapshot = await pollux.inspect_deferred(handle)
        if last_snapshot is None or snapshot != last_snapshot:
            snapshots.append(snapshot)
            last_snapshot = snapshot
        if snapshot.is_terminal:
            return snapshot, snapshots
        await asyncio.sleep(context.poll_interval_seconds)


async def _validation_empty_prompts_rejected(case_dir: Path) -> dict[str, Any]:
    config = Config(
        provider="openai", model=DEFAULT_MODELS["openai"], api_key="test-key"
    )
    message = await _expect_configuration_error(
        case_dir,
        "empty_prompts",
        pollux.defer_many([], config=config),
        "requires at least one prompt",
    )
    return {"checks": [{"name": "empty_prompts", "message": message}]}


async def _validation_legacy_delivery_mode_rejected(case_dir: Path) -> dict[str, Any]:
    config = Config(
        provider="openai", model=DEFAULT_MODELS["openai"], api_key="test-key"
    )
    message = await _expect_configuration_error(
        case_dir,
        "legacy_delivery_mode",
        pollux.defer(
            "Q1?",
            config=config,
            options=Options(delivery_mode="deferred"),
        ),
        "not needed with defer",
    )
    return {"checks": [{"name": "legacy_delivery_mode", "message": message}]}


async def _validation_out_of_scope_options_rejected(case_dir: Path) -> dict[str, Any]:
    config = Config(
        provider="openai", model=DEFAULT_MODELS["openai"], api_key="test-key"
    )
    checks: list[dict[str, str]] = []
    options_to_test = [
        (
            "cache",
            Options(
                cache=CacheHandle(
                    "cache-1", "openai", DEFAULT_MODELS["openai"], time.time() + 3600
                )
            ),
            "cache",
        ),
        (
            "history",
            Options(history=[{"role": "user", "content": "hello"}]),
            "Conversation continuity",
        ),
        (
            "continue_from",
            Options(continue_from={"status": "ok", "answers": []}),
            "Conversation continuity",
        ),
        (
            "tools",
            Options(tools=[{"type": "function", "function": {"name": "f"}}]),
            "Tool calling",
        ),
        ("implicit_caching_true", Options(implicit_caching=True), "implicit_caching"),
        ("implicit_caching_false", Options(implicit_caching=False), "implicit_caching"),
    ]
    for name, options, match in options_to_test:
        message = await _expect_configuration_error(
            case_dir,
            name,
            pollux.defer("Q1?", config=config, options=options),
            match,
        )
        checks.append({"name": name, "message": message})
    return {"checks": checks}


async def _validation_unsupported_provider_rejected(case_dir: Path) -> dict[str, Any]:
    config = Config(
        provider="openrouter",
        model=DEFAULT_MODELS["openrouter"],
        api_key="test-key",
    )
    message = await _expect_configuration_error(
        case_dir,
        "unsupported_provider",
        pollux.defer("Q1?", config=config),
        "does not support deferred delivery",
    )
    return {"checks": [{"name": "unsupported_provider", "message": message}]}


async def _expect_configuration_error(
    case_dir: Path,
    slug: str,
    awaitable: Any,
    expected_substring: str,
) -> str:
    """Await *awaitable* and assert it fails with ConfigurationError."""
    try:
        await awaitable
    except ConfigurationError as exc:
        payload = _serialize_exception(exc)
        _write_json(case_dir / f"{slug}.json", payload)
        _ensure(
            condition=expected_substring in str(exc),
            message=f"expected {expected_substring!r} in {exc!r}",
        )
        return str(exc)
    raise AssertionError(f"{slug} did not raise ConfigurationError")


def _resolve_cases(args: argparse.Namespace) -> list[str]:
    cases = list(args.case or DEFAULT_CASES)
    if args.live_only:
        cases = [case for case in cases if CASE_DESCRIPTIONS[case][0] == "live"]
    if args.validation_only:
        cases = [case for case in cases if CASE_DESCRIPTIONS[case][0] == "validation"]
    return cases


def _resolve_live_providers(
    requested_providers: list[str],
    selected_cases: list[str],
) -> list[ProviderName]:
    live_cases_selected = any(
        CASE_DESCRIPTIONS[case][0] == "live" for case in selected_cases
    )
    if not live_cases_selected:
        return []

    if requested_providers:
        missing = [
            provider
            for provider in requested_providers
            if not os.getenv(ENV_VARS[provider])
        ]
        if missing:
            missing_vars = ", ".join(ENV_VARS[provider] for provider in missing)
            print(
                "Missing API keys for requested live providers: " + missing_vars,
                file=sys.stderr,
            )
            raise SystemExit(2)
        return list(dict.fromkeys(requested_providers))

    available = [
        provider for provider in LIVE_PROVIDERS if os.getenv(ENV_VARS[provider])
    ]
    if available:
        return available

    print(
        "No live providers selected or configured. Set one of "
        "GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY, "
        "or run --validation-only.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _parse_model_overrides(values: list[str]) -> dict[ProviderName, str]:
    overrides: dict[ProviderName, str] = {}
    for raw in values:
        provider, sep, model = raw.partition("=")
        if sep != "=" or provider not in DEFAULT_MODELS or not model:
            raise SystemExit(f"Invalid --model value: {raw!r}. Use PROVIDER=MODEL.")
        overrides[provider] = model
    return overrides


def _ensure(*, condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _serialize_exception(exc: BaseException) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    if isinstance(exc, PolluxError) and exc.hint:
        payload["hint"] = exc.hint
    if isinstance(exc, DeferredNotReadyError):
        payload["snapshot"] = asdict(exc.snapshot)
    return payload


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, DeferredHandle):
        return value.to_dict()
    return str(value)


def _print_record(record: dict[str, Any]) -> None:
    status = "PASS" if record.get("ok") else "FAIL"
    provider = record.get("provider") or "validation"
    model = record.get("model") or "-"
    case = record["case"]
    suffix = ""
    if record.get("error"):
        suffix = f" :: {record['error']['type']}: {record['error']['message']}"
    elif record.get("terminal_snapshot"):
        suffix = f" :: terminal={record['terminal_snapshot']['status']}"
    print(f"{status:<4} {provider:<10} {model:<34} {case}{suffix}", flush=True)


def print_summary(records: list[dict[str, Any]]) -> None:
    """Print a compact run summary."""
    total = len(records)
    passed = sum(1 for record in records if record.get("ok"))
    failed = total - passed
    by_kind: dict[str, int] = {"live": 0, "validation": 0}
    for record in records:
        by_kind[str(record["kind"])] += 1
    print(
        "Summary: "
        f"{passed}/{total} passed, "
        f"{failed} failed, "
        f"live={by_kind['live']}, validation={by_kind['validation']}",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
