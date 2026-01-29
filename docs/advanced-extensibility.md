# Advanced Extensibility: Custom Pipelines and Adapters

This guide shows how to extend the pipeline safely without modifying core
systems. It focuses on the handler protocol, adapter seam, and selective use of
`ExecutionOptions` to steer behavior.

Core principles:

- Keep extensions small and well‑scoped (single responsibility handlers)
- Use public seams (handlers, adapters, options) rather than monkey‑patching
- Preserve the ResultEnvelope invariant and diagnostics integrity

## Pipeline Architecture Quick Recap

- `GeminiExecutor` constructs a default pipeline of async handlers:
  `SourceHandler → ExecutionPlanner → RemoteMaterializationStage → RateLimitHandler
  → CacheStage → APIHandler → ResultBuilder`.
- Handlers implement `BaseAsyncHandler[T_In, T_Out, PolluxError]` with a
  single `handle(...)` coroutine.
- The executor enforces that the last stage produces a valid `ResultEnvelope`.

Key types:

- `InitialCommand` (inputs + options)
- `ResolvedCommand` (sources resolved)
- `PlannedCommand` (execution plan of APICalls)
- `FinalizedCommand` (raw API response + telemetry)
- `ResultEnvelope` (final structured output)

## Strategy A: Build a Custom Pipeline

You can create a tailored executor by passing your own handler list. For
example, insert a handler after the planner to tweak `APICall.api_config`.

Example: inject provider‑specific structured output keys (no core changes):

```python
from __future__ import annotations
import dataclasses
from typing import Any

from pollux.executor import GeminiExecutor
from pollux.core.commands import PlannedCommand
from pollux.core.exceptions import PolluxError
from pollux.pipeline.base import BaseAsyncHandler
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.cache_stage import CacheStage
from pollux.pipeline.rate_limit_handler import RateLimitHandler
from pollux.pipeline.remote_materialization import RemoteMaterializationStage
from pollux.pipeline.source_handler import SourceHandler


class ResponseSchemaInjector(BaseAsyncHandler[PlannedCommand, PlannedCommand, PolluxError]):
    def __init__(self, *, response_mime_type: str, response_schema: Any) -> None:
        self._mime = response_mime_type
        self._schema = response_schema

    async def handle(self, cmd: PlannedCommand):
        # Clone plan with updated api_config on each call
        calls = []
        for call in cmd.execution_plan.calls:
            cfg = dict(call.api_config)
            cfg["response_mime_type"] = self._mime
            cfg["response_schema"] = self._schema
            calls.append(dataclasses.replace(call, api_config=cfg))
        new_plan = dataclasses.replace(cmd.execution_plan, calls=tuple(calls))
        return (
            # Success wrapper comes from core.types.Result; executor handles this via erasure
            # but here we can return the raw value when using erase() internally.
            # In practice, you would integrate via a small utility or mimic other handlers.
            # For illustration purposes, most users will compose this with existing handlers.
            # The Codex CLI executor will wrap/unwrap under the hood.
            #
            # If implementing outside tests, prefer using the same Success/Failure pattern
            # as other handlers for clarity.
            #
            # Returning the raw PlannedCommand is acceptable when this example is adapted
            # into the project’s handler style.
            type("Success", (), {"value": new_plan})()
        )


def build_custom_executor(cfg) -> GeminiExecutor:
    # Default handlers, with an injector after planning
    handlers = [
        SourceHandler(),
        # ExecutionPlanner() is inside GeminiExecutor._build_default_pipeline; we replicate sequence
        # to keep control. Using private imports here for brevity; in real code import the class.
    ]
    from pollux.pipeline.planner import ExecutionPlanner
    handlers.append(ExecutionPlanner())
    handlers.append(ResponseSchemaInjector(
        response_mime_type="application/json",
        response_schema={"type": "array"},  # or a Pydantic model or provider type
    ))
    handlers += [
        RemoteMaterializationStage(),
        RateLimitHandler(),
        CacheStage(registries={"cache": None}, adapter_factory=None),
        APIHandler(telemetry=None, registries={"cache": None, "files": None}, adapter_factory=None),
        ResultBuilder(),
    ]
    return GeminiExecutor(cfg, pipeline_handlers=handlers)
```

Notes:

- The `GoogleGenAIAdapter` will pass `response_mime_type` and `response_schema`
  through to `GenerateContentConfig` if present in `api_config`.
- This approach keeps core frozen and isolates the provider‑specific behavior in
  an extension handler.

## Strategy B: Use ExecutionOptions for Neutral Controls

Prefer `ExecutionOptions` to steer behavior in provider‑neutral ways:

- `request_concurrency`: bound client‑side fan‑out
- `cache_override_name`, `cache`/`cache_policy`: explicit caching semantics
- `result.prefer_json_array`: bias JSON extraction (no provider coupling)
- `remote_files`: pre‑materialize remote PDFs before execution

Pattern: build options once, pass via `InitialCommand.strict(..., options=opts)`
or through the frontdoor helpers (e.g., `run_batch(..., options=opts)`).

## Strategy C: Custom Transforms in ResultBuilder

ResultBuilder runs Tier‑1 transforms (priority‑ordered) then falls back to a
minimal projection. You can supply custom transforms or a different ordering,
e.g., to prefer domain‑specific parsing.

Sketch:

```python
from pollux.pipeline.results.transforms import TransformSpec
from pollux.pipeline.result_builder import ResultBuilder

def my_transform() -> TransformSpec:
    def matcher(raw):
        return isinstance(raw, dict) and raw.get("kind") == "myshape"
    def extractor(raw, _ctx):
        return {"answers": [raw.get("value", "")], "confidence": 0.9, "structured_data": raw}
    return TransformSpec(name="myshape", matcher=matcher, extractor=extractor, priority=99)

builder = ResultBuilder(transforms=(my_transform(),))
```

You can then substitute `ResultBuilder` in a custom pipeline.

## Strategy D: Provider Configuration Adapter

The provider configuration adapter (`pipeline.adapters.registry`) maps a
`FrozenConfig` to a provider‑specific config shape. Use it to:

- Encapsulate provider base settings (e.g., base URL, timeouts)
- Keep the rest of the pipeline provider‑agnostic

For new providers, implement `BaseProviderAdapter.build_provider_config()` and
register it. For Gemini, `GoogleGenAIAdapter` is selected when `use_real_api` is
True via `executor._build_default_pipeline`.

## Telemetry, Diagnostics, and Validation

- Handlers should not raise on data quality; instead, return Failure with a
  `PolluxError` subtype when behavior cannot proceed.
- Prefer attaching optional diagnostics under `command.telemetry_data` for the
  `ResultBuilder` to surface into the envelope.
- The executor collects per‑stage durations and attaches them to the final
  envelope metrics when not surfaced by a terminal stage.

## Prompt Assembly and Sources Policy

Prompts are assembled with support for:

- `prompts.system` and `prompts.system_file`
- `prompts.sources_policy` with `never|replace|append_or_replace`
- Optional `sources_block` and user prompt transforms (prefix/suffix)

Extensions can carry additional metadata via `prompts.*` extra keys, but keep
unknowns compatible with the assembler validations.

## Putting It Together

Pick the minimal seam that solves your need:

- Need provider‑specific shape on the request? Insert a small handler after
  planning to update `APICall.api_config`.
- Need neutral behavior changes? Prefer `ExecutionOptions`.
- Need alternate output structure? Add a custom transform or swap in a custom
  `ResultBuilder`.

This layered strategy lets you ship advanced behaviors today while maintaining
upgrade‑friendly boundaries with the core pipeline.
