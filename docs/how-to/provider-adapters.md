# Provider Adapters — How‑To

> Audience: developers adding a new provider integration. The library is provider‑neutral; Gemini is implemented, and you can inject your own adapter for other providers.

!!! info "See also"
    - Concepts: [Provider Capabilities](../explanation/concepts/provider-capabilities.md)
    - Concepts: [API Execution](../explanation/concepts/api-execution.md)
    - Deep‑Dive: [Command Pipeline Spec](../explanation/deep-dives/command-pipeline-spec.md)

---

## What you are implementing

Execution adapters implement the minimal surface used by the API handler:

- Required:
  - `GenerationAdapter.generate(model_name, api_parts, api_config) -> dict`
- Optional capabilities (duck‑typed):
  - `UploadsCapability.upload_file_local(path, mime_type) -> Any`
  - `CachingCapability.create_cache(model_name, content_parts, system_instruction, ttl_seconds) -> str`
  - `ExecutionHintsAware.apply_hints(hints) -> None`

Additionally, a configuration adapter can customize provider‑specific config shapes:

- `ProviderAdapter.build_provider_config(cfg: FrozenConfig) -> Mapping[str, Any]`

Locations in code:

- Protocols: `pollux.pipeline.adapters.base`
- Provider config registry: `pollux.pipeline.adapters.registry`
- Example implementation: `pollux.pipeline.adapters.gemini`

---

## Minimal execution adapter example

```python
from __future__ import annotations
from typing import Any

from pollux.pipeline.adapters.base import GenerationAdapter

class MyProviderAdapter(GenerationAdapter):
    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:
        # 1) Convert neutral api_parts to provider request
        # 2) Call your provider SDK
        # 3) Return a minimal raw dict compatible with ResultBuilder
        #    Shape options that work with built‑ins:
        #      {"text": "...", "model": model_name}
        #      or {"candidates": [{"content": {"parts": [{"text": "..."}]}}], "model": model_name}
        return {"text": "hello from my provider", "model": model_name}
```

If your provider supports uploads and/or caching, also implement these methods:

```python
from pollux.pipeline.adapters.base import UploadsCapability, CachingCapability

class MyProviderAdapter(GenerationAdapter, UploadsCapability, CachingCapability):
    async def upload_file_local(self, path, mime_type):
        # Return a provider reference object or dict
        return {"uri": f"myprov://{path}", "mime_type": mime_type}

    async def create_cache(self, *, model_name, content_parts, system_instruction, ttl_seconds):
        # Create and return a cache identifier used by subsequent generate calls
        return "cache/123"
```

Tips

- Keep the adapter small; translate between neutral types and your SDK.
- Normalize outputs to include either a top‑level `text` or a `candidates[0].content.parts[0].text` shape; the default transforms handle both, with a minimal fallback.
- Avoid leaking your SDK types beyond the adapter boundary; use plain dicts and simple objects.

---

## Injecting your adapter

There are two common ways to use your adapter.

1) Provide it directly to the API handler and compose a pipeline:

```python
from pollux.pipeline import SourceHandler
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.rate_limit_handler import RateLimitHandler
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.result_builder import ResultBuilder

adapter = MyProviderAdapter(...)
handlers = [
    SourceHandler(),
    ExecutionPlanner(),
    RateLimitHandler(),
    APIHandler(adapter=adapter),
    ResultBuilder(),
]

# Use with your executor or a simple loop similar to GeminiExecutor
```

2) Provide a factory to the API handler (useful if you need an API key or per‑run setup):

```python
from pollux.pipeline.api_handler import APIHandler

def adapter_factory(api_key: str) -> MyProviderAdapter:
    return MyProviderAdapter(api_key)

handler = APIHandler(adapter_factory=adapter_factory)
```

Note

- The built‑in `GeminiExecutor` wires a Gemini adapter when `use_real_api=True`. For other providers, create a custom executor (or override the pipeline) and pass your adapter or factory to `APIHandler`.

---

## Optional: provider‑specific configuration

If you need to transform `FrozenConfig` into a provider‑specific mapping, implement and register a configuration adapter:

```python
from typing import Any, Mapping
from pollux.pipeline.adapters.base import BaseProviderAdapter
from pollux.pipeline.adapters.registry import register_adapter

class MyProviderConfigAdapter(BaseProviderAdapter):
    name = "myprovider"  # Match your provider slug
    def build_provider_config(self, cfg) -> Mapping[str, Any]:
        return {
            "model": cfg.model,
            "api_key": cfg.api_key,
            "timeout_s": cfg.extra.get("timeout_s", 30),
        }

register_adapter(MyProviderConfigAdapter())
```

You can retrieve this mapping via `build_provider_config(provider, cfg)` if you customize your executor.

---

## Testing guidance

- Implement a deterministic mock path for local tests or use VCR‑style fixtures.
- Add contract tests for your adapter protocol conformance and graceful degradation:
  - Generation required; uploads/caching conditional.
- Mark slow/real API tests with `-m api` or `-m slow` to keep the default suite fast.
- Validate the output shape works with the default `ResultBuilder` transforms; add a tiny extractor if needed.

---

## Troubleshooting

- Pipeline errors referencing “Uploads required but not supported” indicate your plan includes uploads; either implement `UploadsCapability` or adjust your plan to inline content.
- If results are empty, ensure your adapter returns either `{"text": ...}` or a `candidates[0].content.parts[0].text` path.
- For caching, if retries happen without cache, confirm `create_cache` returns a stable identifier and that `cached_content` is plumbed by your adapter.

---
