"""Scenario-first convenience helpers for common operations.

These functions provide a minimal "pit of success" entrypoint over the
underlying executor and command pipeline, without changing core behavior.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from typing import TYPE_CHECKING, Any, Literal, overload

from pollux.core.concurrency import resolve_request_concurrency
from pollux.core.execution_options import (
    ExecutionOptions,
    ResultOption,
    make_execution_options,
)
from pollux.core.types import InitialCommand, Source
from pollux.executor import Executor, create_executor

# Extraction method constant used by parallel aggregate helper
PARALLEL_AGG_METHOD = "parallel_aggregate"

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Coroutine, Iterable

    from pollux.config import FrozenConfig
    from pollux.types import ResultEnvelope


def _resolve_config() -> FrozenConfig:
    from pollux.config import resolve_config

    return resolve_config()


async def run_simple(
    prompt: str,
    *,
    source: Source | None = None,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> ResultEnvelope:
    """Run a simple query (optionally RAG on a single source).

    Args:
        prompt: The user prompt to execute.
        source: A single explicit `types.Source`. Use `types.Source.from_text()`
            for text content or `types.Source.from_file()` for files. Strings
            are not accepted directly to avoid ambiguity.
        cfg: Optional frozen configuration. If omitted, `resolve_config()` is used.
        prefer_json: Hint the extractor to prefer JSON array when reasonable.
        options: Advanced structured execution options. If provided and
            `prefer_json` is also True, the JSON preference is merged only
            when `options.result` is not set.
            Note: This simple helper executes a single API call; a concurrency
            bound is not applicable here.

    Returns:
        Result envelope dictionary.

    Example:
        ```python
        from pollux import types

        # Simple text analysis
        result = await run_simple(
            "What is the main theme?",
            source=types.Source.from_text("Long text..."),
        )

        # File analysis
        result = await run_simple(
            "Summarize this document",
            source=types.Source.from_file("report.pdf"),
        )
        ```

    See Also:
        For advanced control, use `Executor` directly.
        For multiple prompts, use `run_batch()`.
    """
    final_cfg = cfg or _resolve_config()
    executor: Executor = create_executor(final_cfg)

    sources: tuple[Source, ...] = (source,) if source is not None else ()

    # Build or merge options for result preferences; caching follows configuration
    opts = _merge_frontdoor_options(
        prefer_json=prefer_json, options=options, concurrency=None
    )

    cmd = InitialCommand.strict(
        sources=sources,
        prompts=(str(prompt),),
        config=executor.config,
        options=opts,
    )
    return await executor.execute(cmd)


# Note for maintainers:
# These overloads return a Coroutine to keep strict typing correct for async
# functions. The implementation is `async def`, so callers should `await` the
# returned value to get a `ResultEnvelope`.
@overload
def run_batch(
    prompts: str,
    sources: Iterable[Source] = (),
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
    concurrency: int | None = None,
) -> Coroutine[Any, Any, ResultEnvelope]: ...


@overload
def run_batch(
    prompts: Iterable[str],
    sources: Iterable[Source] = (),
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
    concurrency: int | None = None,
) -> Coroutine[Any, Any, ResultEnvelope]: ...


async def run_batch(
    prompts: Iterable[str],
    sources: Iterable[Source] = (),
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
    concurrency: int | None = None,
) -> ResultEnvelope:
    """Run multiple prompts over one or many sources efficiently.

    Covers multi-question analysis, complex synthesis, and parallel batch by
    relying on the planner's vectorization of prompts with shared context.

    Behavior:
        - Vectorized execution shares prepared context across calls.
        - API calls may execute sequentially or with bounded fan-out depending
          on rate constraints and `request_concurrency` (in options or config).
          Uploads may be performed concurrently during preparation.

    Args:
        prompts: One or more user prompts. Accepts a single string or an
            iterable of strings; a single string is treated as one prompt.
        sources: Zero or more explicit `types.Source` objects. Use
            `types.Source.from_text()` for text content or
            `types.Source.from_file()` for files. Strings are not accepted
            directly to avoid ambiguity. For directories, use the explicit
            helper `types.sources_from_directory(path)`.
        cfg: Optional frozen configuration; resolved if omitted.
        prefer_json: Hint extractor to prefer JSON array when reasonable.
        options: Advanced structured execution options. If provided and
            `prefer_json` is also True, the JSON preference is merged only
            when `options.result` is not set.
        concurrency: Optional client-side fan-out bound for vectorized calls.
            Mirrors `ExecutionOptions.request_concurrency` (overrides config
            default for this call). When constrained by a rate limit, fan-out
            is forced to 1 regardless of this setting.

    Returns:
        Result envelope dictionary with answers ordered by prompts.

    Example:
        ```python
        from pollux import types

        # Multi-question analysis
        questions = ["What are the key themes?", "Who are the main characters?"]
        result = await run_batch(
            questions, sources=[types.Source.from_file("story.txt")]
        )

        # Batch processing
        result = await run_batch(
            prompts=["Analyze tone", "Extract quotes"],
            sources=[types.Source.from_file("large_document.pdf")],
        )

        # Directory expansion (explicit helper)
        result = await run_batch(
            prompts=["Index files"],
            sources=types.sources_from_directory("docs/"),
        )
        ```

    See Also:
        For single prompts, use `run_simple()`.
        For advanced pipeline control, use `Executor` with `InitialCommand`.
    """
    final_cfg = cfg or _resolve_config()
    executor: Executor = create_executor(final_cfg)

    # No implicit path detection; callers must pass explicit Sources
    resolved_sources: list[Source] = list(sources)

    # Coerce prompts eagerly; treat a single string as one prompt
    prompt_list = [prompts] if isinstance(prompts, str) else [str(p) for p in prompts]

    # Build or merge options for result preferences; caching follows configuration
    opts = _merge_frontdoor_options(
        prefer_json=prefer_json, options=options, concurrency=concurrency
    )

    cmd = InitialCommand.strict(
        sources=tuple(resolved_sources),
        prompts=tuple(prompt_list),
        config=executor.config,
        options=opts,
    )
    return await executor.execute(cmd)


# --- Scenario-named helpers (thin wrappers for clarity) ---
async def run_rag(
    question: str,
    source: Source,
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> ResultEnvelope:
    """RAG: Single question over a single source.

    Notes:
        - Uses the vectorized execution path even for one prompt to keep
          behavior uniform with batching.
        - API calls are executed sequentially in the current engine; file
          uploads may be performed concurrently.
    """
    return await run_batch(
        [question],
        [source],
        cfg=cfg,
        prefer_json=prefer_json,
        options=options,
    )


@overload
def run_multi(
    prompts: str,
    source: Source,
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> Coroutine[Any, Any, ResultEnvelope]: ...


@overload
def run_multi(
    prompts: Iterable[str],
    source: Source,
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> Coroutine[Any, Any, ResultEnvelope]: ...


async def run_multi(
    prompts: Iterable[str] | str,
    source: Source,
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> ResultEnvelope:
    """Multiple prompts over a single shared source (vectorized).

    Notes:
        - Vectorized path reuses shared context; API calls are executed
          sequentially; uploads may run concurrently.
        - To bound client-side fan-out, pass
          `options=make_execution_options(request_concurrency=...)` or use
          `run_batch(..., concurrency=...)`.
    """
    if isinstance(prompts, str):
        return await run_batch(
            [prompts],
            [source],
            cfg=cfg,
            prefer_json=prefer_json,
            options=options,
        )
    return await run_batch(
        prompts,
        [source],
        cfg=cfg,
        prefer_json=prefer_json,
        options=options,
    )


@overload
def run_synthesis(
    prompts: str,
    sources: Iterable[Source],
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> Coroutine[Any, Any, ResultEnvelope]: ...


@overload
def run_synthesis(
    prompts: Iterable[str],
    sources: Iterable[Source],
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> Coroutine[Any, Any, ResultEnvelope]: ...


async def run_synthesis(
    prompts: Iterable[str] | str,
    sources: Iterable[Source],
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
) -> ResultEnvelope:
    """Complex synthesis: many prompts x many sources with shared context.

    Notes:
        - Uses vectorized execution; API calls execute sequentially; uploads
          may be concurrent.
        - To bound client-side fan-out, pass
          `options=make_execution_options(request_concurrency=...)` or use
          `run_batch(..., concurrency=...)`.
    """
    if isinstance(prompts, str):
        return await run_batch(
            [prompts],
            sources,
            cfg=cfg,
            prefer_json=prefer_json,
            options=options,
        )
    return await run_batch(
        prompts,
        sources,
        cfg=cfg,
        prefer_json=prefer_json,
        options=options,
    )


async def run_parallel(
    prompt: str,
    sources: Iterable[Source],
    *,
    cfg: FrozenConfig | None = None,
    prefer_json: bool = False,
    options: ExecutionOptions | None = None,
    concurrency: int | None = None,
) -> ResultEnvelope:
    """Same question over many sources with per-source concurrency.

    Behavior:
        - Fans out one request per source concurrently, then aggregates
          answers in source order. This mirrors the pattern shown in
          examples scenario 5 and typically yields latency near the max
          of per-source durations (subject to rate limits).
        - Uses the same executor/config for all tasks.

    Notes:
        - For a single vectorized request (shared context) without fan-out,
          use `run_batch([prompt], sources=...)` instead.
    """
    final_cfg = cfg or _resolve_config()
    executor: Executor = create_executor(final_cfg)
    opts = _merge_frontdoor_options(
        prefer_json=prefer_json, options=options, concurrency=concurrency
    )

    src_list = list(sources)

    # Bound client-side fan-out using shared resolver (sequential when constrained)
    # Rate limiting still applies on the provider side.
    resolved_conc = resolve_request_concurrency(
        n_calls=len(src_list),
        options=opts,
        cfg=final_cfg,
        rate_constrained=False,
    )
    sem = asyncio.Semaphore(max(1, resolved_conc))

    async def _one(src: Source) -> ResultEnvelope:
        async with sem:
            cmd = InitialCommand.strict(
                sources=(src,),
                prompts=(str(prompt),),
                config=executor.config,
                options=opts,
            )
            return await executor.execute(cmd)

    gathered = await asyncio.gather(
        *(_one(s) for s in src_list), return_exceptions=True
    )

    # Aggregate answers and basic metrics
    answers: list[str] = []
    confidences: list[float] = []
    total_tokens = 0
    per_prompt: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, res in enumerate(gathered):
        # Stable source identifier for mapping results
        src = src_list[idx]
        src_id = str(src.identifier)
        if isinstance(res, BaseException):
            answers.append("")
            per_prompt.append(
                {
                    "index": idx,
                    "source_id": src_id,
                    "error": str(res),
                }
            )
            errors.append({"index": idx, "error": str(res)})
            continue
        env = res
        # answers
        a = env.get("answers", [])
        answers.append(str(a[0] if a else ""))
        # confidence
        c = env.get("confidence")
        if isinstance(c, int | float):
            confidences.append(float(c))
        # usage
        u = env.get("usage")
        if isinstance(u, dict):
            with contextlib.suppress(Exception):
                total_tokens += int(u.get("total_token_count", 0) or 0)
        # per-call metrics snapshot
        per_prompt.append(
            {
                "index": idx,
                "source_id": src_id,
                "durations": dict(env.get("metrics", {}).get("durations", {}))
                if isinstance(env.get("metrics", {}).get("durations"), dict)
                else {},
                "usage": dict(u) if isinstance(u, dict) else {},
                "extraction_method": env.get("extraction_method"),
            }
        )

    # Determine aggregate status based on per-call outcomes
    error_count = len(errors)
    status: Literal["ok", "partial", "error"]
    if error_count == len(src_list) and len(src_list) > 0:
        status = "error"
    elif error_count > 0:
        status = "partial"
    else:
        status = "ok"

    envelope: ResultEnvelope = {
        "status": status,
        "answers": answers,
        "extraction_method": PARALLEL_AGG_METHOD,
        "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "metrics": {
            "per_prompt": tuple(per_prompt),
            "parallel_n_calls": len(src_list),
            "parallel_errors": error_count,
        },
        "usage": {"total_token_count": total_tokens},
    }
    if error_count:
        envelope["diagnostics"] = {
            "parallel_errors": error_count,
            "errors": tuple(errors),
        }
    return envelope


# --- Internal helpers ---


def _merge_frontdoor_options(
    *,
    prefer_json: bool,
    options: ExecutionOptions | None,
    concurrency: int | None,
) -> ExecutionOptions | None:
    """Return ExecutionOptions merging JSON preference and concurrency.

    - Construct options if none provided and a preference is requested.
    - Inject `result` only when absent.
    - Inject `request_concurrency` when an explicit value is provided.
    """
    # When no options supplied, construct only if any preference is requested
    if options is None:
        if not prefer_json and concurrency is None:
            return None
        return make_execution_options(
            result_prefer_json_array=bool(prefer_json),
            request_concurrency=concurrency,
        )

    updated = options
    if prefer_json and updated.result is None:
        updated = dataclasses.replace(
            updated, result=ResultOption(prefer_json_array=True)
        )
    if concurrency is not None:
        updated = dataclasses.replace(updated, request_concurrency=concurrency)
    return updated
