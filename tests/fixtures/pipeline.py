"""Pipeline- and adapter-focused fixtures.

Includes legacy client shims, executor builders, and HTTP/mime mocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def mock_gemini_client(mock_env):  # noqa: ARG001
    """Provide a MagicMock for the legacy GeminiClient interface (compat shim)."""
    mock_client = MagicMock()
    mock_client.generate_content.return_value = {
        "text": '["Default mock answer"]',
        "usage": {
            "prompt_tokens": 10,
            "candidates_token_count": 5,
            "total_tokens": 15,
        },
    }
    return mock_client


@pytest.fixture
def batch_processor(mock_gemini_client):  # noqa: ARG001
    """Provide a BatchProcessor-like adapter using the new executor."""
    from pollux.config import resolve_config
    from pollux.core.types import InitialCommand, ResultEnvelope
    from pollux.executor import GeminiExecutor

    class _TestAdapterBatchProcessor:
        def __init__(self, **config_overrides: Any):
            programmatic: dict[str, Any] = {
                "api_key": config_overrides.get("api_key", "mock_api_key_for_tests"),
                "model": config_overrides.get("model", "gemini-2.0-flash"),
                "enable_caching": config_overrides.get("enable_caching", False),
                "use_real_api": config_overrides.get("use_real_api", False),
            }
            if "tier" in config_overrides:
                programmatic["tier"] = config_overrides["tier"]
            if "ttl_seconds" in config_overrides:
                programmatic["ttl_seconds"] = config_overrides["ttl_seconds"]

            self.config = resolve_config(overrides=programmatic)
            self.executor = GeminiExecutor(config=self.config)

        def process_questions(
            self,
            content: Any,
            questions: list[str],
            _compare_methods: bool = False,  # noqa: FBT001, FBT002
            _response_schema: Any | None = None,
            _return_usage: bool = False,  # noqa: FBT001, FBT002
            **_kwargs: Any,
        ) -> ResultEnvelope:
            sources = tuple(content) if isinstance(content, list) else (content,)
            prompts = tuple(questions)
            command = InitialCommand(
                sources=sources, prompts=prompts, config=self.config
            )

            import asyncio

            try:
                return asyncio.run(self.executor.execute(command))
            except Exception as e:  # pragma: no cover - defensive bridge
                return {
                    "status": "error",
                    "answers": [],
                    "extraction_method": "error",
                    "confidence": 0.0,
                    "metrics": {"error": str(e)},
                    "usage": {},
                }

        def process_questions_multi_source(
            self,
            sources: list[Any],
            questions: list[str],
            response_schema: Any | None = None,
            **kwargs: Any,
        ) -> ResultEnvelope:
            flat_sources: list[Any] = []
            for src in sources:
                if isinstance(src, list):
                    flat_sources.extend(src)
                else:
                    flat_sources.append(src)
            return self.process_questions(
                content=flat_sources,
                questions=questions,
                response_schema=response_schema,
                **kwargs,
            )

    return _TestAdapterBatchProcessor(api_key="mock_api_key_for_tests")


@pytest.fixture
def char_executor(mock_gemini_client):
    """Provide a GeminiExecutor wired with a controllable test adapter."""
    from pollux.config import resolve_config
    from pollux.executor import GeminiExecutor
    from pollux.pipeline.adapters.base import (
        CachingCapability,
        ExecutionHintsAware,
        GenerationAdapter,
    )
    from pollux.pipeline.api_handler import APIHandler
    from pollux.pipeline.cache_stage import CacheStage
    from pollux.pipeline.execution_state import ExecutionHints
    from pollux.pipeline.rate_limit_handler import RateLimitHandler
    from pollux.pipeline.result_builder import ResultBuilder
    from pollux.pipeline.source_handler import SourceHandler

    class _Adapter(GenerationAdapter, CachingCapability, ExecutionHintsAware):
        def __init__(self) -> None:
            self._hints: ExecutionHints | None = None
            self.interaction_log: list[dict[str, object]] | None = None
            self.queue: list[dict[str, Any]] = []

        def apply_hints(self, hints: Any) -> None:
            if isinstance(hints, ExecutionHints):
                self._hints = hints

        async def create_cache(
            self,
            *,
            model_name: str,  # noqa: ARG002
            content_parts: tuple[Any, ...],  # noqa: ARG002
            system_instruction: str | None,  # noqa: ARG002
            ttl_seconds: int | None,  # noqa: ARG002
        ) -> str:
            name = "cachedContents/mock-cache-123"
            if self.interaction_log is not None:
                self.interaction_log.append({"method": "caches.create"})
            return name

        async def generate(
            self,
            *,
            model_name: str,  # noqa: ARG002
            api_parts: tuple[Any, ...],
            api_config: dict[str, object],
        ) -> dict[str, Any]:
            if self.queue:
                return self.queue.pop(0)
            if self.interaction_log is not None:
                cached_value = cast("str | None", api_config.get("cached_content"))
                entry: dict[str, object] = {"method": "generate_content"}
                if cached_value is not None:
                    entry["cached_content"] = cached_value
                self.interaction_log.append(entry)

            if hasattr(mock_gemini_client, "generate_content"):
                fn = mock_gemini_client.generate_content
                se = getattr(fn, "side_effect", None)
                if callable(se) or isinstance(se, list):
                    if isinstance(se, list):
                        return cast("dict[str, Any]", se.pop(0))
                    return cast("dict[str, Any]", fn.side_effect())
                rv = getattr(fn, "return_value", None)
                if isinstance(rv, dict):
                    return cast("dict[str, Any]", rv)

            text = ""
            try:
                part0 = next(iter(api_parts))
                text = getattr(part0, "text", str(part0))
            except StopIteration:
                text = ""
            return {"text": text, "usage": {"total_token_count": 0}}

    adapter = _Adapter()

    def make_executor(
        *, interaction_log: list[dict[str, object]] | None = None
    ) -> GeminiExecutor:
        from pollux.pipeline.planner import ExecutionPlanner
        from pollux.pipeline.registries import CacheRegistry

        cfg = resolve_config(
            overrides={
                "api_key": "mock_api_key_for_tests",
                "model": "gemini-2.0-flash",
                "enable_caching": True,
                "use_real_api": False,
            }
        )
        adapter.interaction_log = interaction_log
        cache_reg = CacheRegistry()
        pipeline: list[Any] = [
            SourceHandler(),
            ExecutionPlanner(),
            RateLimitHandler(),
            CacheStage(
                registries={"cache": cache_reg}, adapter_factory=lambda _k: adapter
            ),
            APIHandler(adapter=adapter, registries={"cache": cache_reg}),
            ResultBuilder(),
        ]
        return GeminiExecutor(cfg, pipeline_handlers=pipeline)

    class _Exec:
        def __init__(self, factory: Callable[..., GeminiExecutor]):
            self._factory = factory
            self.adapter = adapter

        def build(
            self, *, interaction_log: list[dict[str, object]] | None = None
        ) -> GeminiExecutor:
            return self._factory(interaction_log=interaction_log)

    return _Exec(make_executor)


@pytest.fixture
def mocked_internal_genai_client():
    """Patch google.genai.Client internals for adapter testing."""
    with patch("google.genai.Client") as mock_genai:
        mock_instance = mock_genai.return_value
        mock_instance.caches.create.return_value = MagicMock(
            name="caches.create_return",
        )
        type(mock_instance.caches.create.return_value).name = PropertyMock(
            return_value="cachedContents/mock-cache-123",
        )
        mock_instance.models.count_tokens.return_value = MagicMock(total_tokens=5000)
        yield mock_instance


@pytest.fixture
def caching_gemini_client(mock_env, mocked_internal_genai_client):  # noqa: ARG001
    mock_client = MagicMock()
    mock_client.enable_caching = True
    return mock_client


@pytest.fixture
def mock_httpx_client():
    """Yield a bare httpx client mock; patch where used in tests.

    This fixture does not patch any module by default. Tests should patch the
    specific import site (e.g., via ``monkeypatch``) and supply this mock.
    """
    yield MagicMock()


@pytest.fixture
def mock_get_mime_type():
    """Deprecated shim for legacy MIME detection hooks.

    Prefer MIME detection inside ``Source.from_file``. This fixture remains for
    compatibility and is slated for removal once all legacy tests migrate.
    """
    m = MagicMock()
    m.side_effect = lambda *_a, **_k: "application/octet-stream"
    yield m
