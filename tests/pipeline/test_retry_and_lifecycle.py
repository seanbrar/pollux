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
)
from pollux.providers.models import (
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
)
from pollux.retry import RetryPolicy
from pollux.source import Source
from tests.conftest import (
    GEMINI_MODEL,
    FakeProvider,
)

pytestmark = pytest.mark.integration


# =============================================================================
# Provider Lifecycle (Boundary)
# =============================================================================


@pytest.mark.asyncio
async def test_provider_is_closed_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider cleanup should run and must not mask success/failure."""

    @dataclass
    class _Provider(FakeProvider):
        closed: int = 0
        fail_generate: bool = False
        fail_close: bool = False

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            if self.fail_generate:
                raise APIError("bad request", retryable=False, status_code=400)
            return await super().generate(request)

        async def aclose(self) -> None:
            self.closed += 1
            if self.fail_close:
                raise RuntimeError("close failed")

    scenarios: list[tuple[str, bool, bool]] = [
        ("success + close ok", False, False),
        ("success + close fails", False, True),
        ("generate fails + close fails", True, True),
    ]

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    for name, fail_generate, fail_close in scenarios:
        fake = _Provider(fail_generate=fail_generate, fail_close=fail_close)
        monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake: _fake)

        if fail_generate:
            with pytest.raises(APIError, match="bad request"):
                await pollux.run("Q", config=cfg)
        else:
            result = await pollux.run("Q", config=cfg)
            assert result.metrics.completion_status == "clean"

        assert fake.closed == 1, name


# =============================================================================
# Retry Behavior (Boundary)
# =============================================================================


@pytest.mark.asyncio
async def test_retry_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Retry should behave predictably for generate and side effects."""

    retry = RetryPolicy(
        max_attempts=2,
        initial_delay_s=0.0,
        max_delay_s=0.0,
        jitter=False,
    )

    @dataclass
    class _Provider(FakeProvider):
        mode: str = "generate_retry"
        generate_calls: int = 0
        upload_attempts: int = 0

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            self.generate_calls += 1
            if self.mode == "generate_retry" and self.generate_calls == 1:
                raise APIError("rate limited", retryable=True, status_code=429)
            if self.mode == "generate_no_retry":
                raise APIError("bad request", retryable=False, status_code=400)

            # Upload scenarios: verify substitution happened before generate().
            if self.mode.startswith("upload_"):
                parts = request.parts
                assert any(
                    isinstance(p, ProviderFileAsset)
                    and p.file_id == "mock://uploaded/doc.txt"
                    for p in parts
                )
            return ProviderResponse(text="ok", usage={"total_tokens": 1})

        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:
            _ = path, mime_type
            self.upload_attempts += 1
            if self.mode == "upload_retry" and self.upload_attempts == 1:
                raise APIError(
                    "rate limited",
                    retryable=True,
                    status_code=429,
                    retry_after_s=0.0,
                )
            if self.mode == "upload_no_retry":
                raise APIError("upload timed out", provider="gemini", phase="upload")
            return ProviderFileAsset(
                file_id="mock://uploaded/doc.txt", provider="mock", mime_type=mime_type
            )

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    scenarios: list[tuple[str, bool, int, int]] = [
        ("generate_retry", True, 2, 0),
        ("generate_no_retry", False, 1, 0),
        ("upload_retry", True, 1, 2),
        ("upload_no_retry", False, 0, 1),
    ]

    for mode, expect_ok, expect_generate_calls, expect_upload_attempts in scenarios:
        fake = _Provider(mode=mode)
        monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake: _fake)
        cfg = Config(
            provider="gemini",
            model=GEMINI_MODEL,
            use_mock=True,
            retry=retry,
        )

        if mode.startswith("upload_"):
            coro = pollux.run(
                "Read this",
                source=Source.from_file(file_path),
                config=cfg,
            )
        else:
            coro = pollux.run("hello", config=cfg)

        if expect_ok:
            result = await coro
            assert result.text == "ok"
        else:
            with pytest.raises(APIError):
                await coro

        assert fake.generate_calls == expect_generate_calls
        assert fake.upload_attempts == expect_upload_attempts


@pytest.mark.asyncio
async def test_retry_skipped_for_permanent_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that permanent errors like context_overflow or auth_refreshable do not trigger retries."""
    retry = RetryPolicy(
        max_attempts=3,
        initial_delay_s=0.0,
        max_delay_s=0.0,
        jitter=False,
    )

    @dataclass
    class _FailingProvider(FakeProvider):
        calls: int = 0
        error_type: str = "context_overflow"

        async def generate(self, _request: ProviderRequest) -> ProviderResponse:
            self.calls += 1
            if self.error_type == "context_overflow":
                raise APIError(
                    "context length exceeded limit",
                    retryable=True,  # force True to verify category override
                    status_code=400,
                    error_category="context_overflow",
                )
            raise APIError(
                "unauthorized access",
                retryable=True,
                status_code=401,
                error_category="auth_refreshable",
            )

    cfg = Config(
        provider="gemini",
        model=GEMINI_MODEL,
        use_mock=True,
        retry=retry,
    )

    # 1. Test context_overflow
    fake = _FailingProvider(error_type="context_overflow")
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake: _fake)
    with pytest.raises(APIError, match="context length"):
        await pollux.run("hello", config=cfg)
    assert fake.calls == 1  # Should only run once, not retried!

    # 2. Test auth_refreshable
    fake2 = _FailingProvider(error_type="auth_refreshable")
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake2: _fake)
    with pytest.raises(APIError, match="unauthorized"):
        await pollux.run("hello", config=cfg)
    assert fake2.calls == 1  # Should only run once, not retried!
