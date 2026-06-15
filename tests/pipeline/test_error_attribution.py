"""Pipeline boundary tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import pollux
import pollux.cache
from pollux.config import Config
from pollux.errors import (
    APIError,
    ConfigurationError,
    PlanningError,
)
from pollux.providers import _compile
from pollux.providers.models import (
    ProviderFileAsset,
    ProviderResponse,
)
from pollux.retry import RetryPolicy
from pollux.source import Source
from tests.conftest import (
    GEMINI_MODEL,
    OPENAI_MODEL,
    FakeProvider,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_generate_error_attributes_provider_and_call_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generate failures should carry provider, phase, and call index."""

    @dataclass
    class _Provider(FakeProvider):
        async def generate(
            self, snapshot: Any, input: Any, requirements: Any, config: Any
        ) -> ProviderResponse:
            parts = _compile.request_parts(snapshot, input)
            prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
            if prompt == "Q2":
                raise APIError(
                    "bad request",
                    retryable=False,
                    status_code=400,
                    provider="gemini",
                    phase="generate",
                )
            return ProviderResponse(text="ok", usage={"total_tokens": 1})

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    cfg = Config(
        provider="gemini",
        model=GEMINI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(APIError) as exc:
        await pollux.run_many(prompts=("Q1", "Q2"), config=cfg)

    err = exc.value
    assert err.provider == "gemini"
    assert err.phase == "generate"
    assert err.call_idx == 1


@pytest.mark.asyncio
async def test_upload_error_attributes_provider_and_call_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Upload failures should carry provider, phase, and call index."""

    @dataclass
    class _Provider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            raise APIError(
                "upload failed",
                retryable=False,
                provider="openai",
                phase="upload",
            )

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(
        provider="openai",
        model=OPENAI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(APIError) as exc:
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path),
            config=cfg,
        )

    err = exc.value
    assert err.provider == "openai"
    assert err.phase == "upload"
    assert err.call_idx == 0


@pytest.mark.asyncio
async def test_upload_configuration_errors_propagate_without_internal_wrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Provider-side upload validation should stay a ConfigurationError."""

    @dataclass
    class _Provider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            raise ConfigurationError(
                f"unsupported mime type: {mime_type}",
                hint="Only PDFs are supported.",
            )

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    file_path = tmp_path / "data.csv"
    file_path.write_text("a,b\n1,2\n", encoding="utf-8")

    cfg = Config(
        provider="openrouter",
        model=OPENAI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(ConfigurationError, match="unsupported mime type: text/csv"):
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path, mime_type="text/csv"),
            config=cfg,
        )


@pytest.mark.asyncio
async def test_planning_error_wraps_source_loader_failure() -> None:
    """Source loader failures should surface as PlanningError with context."""

    def _boom() -> bytes:
        raise RuntimeError("boom")

    bad = Source(
        source_type="text",
        identifier="bad-source",
        mime_type="text/plain",
        size_bytes=0,
        content_loader=_boom,
    )

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(PlanningError, match="Failed to load content"):
        await pollux.run_many(
            ("Q",),
            sources=(bad,),
            config=cfg,
        )
