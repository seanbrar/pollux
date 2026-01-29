"""Pipeline boundary tests.

Tests the complete flow from InitialCommand to ResultEnvelope, and verifies
critical internal behaviors (single-flight caching, upload deduplication,
remote materialization) that protect against real failure modes.

This file is the backbone of the test suite—tests here exercise real paths
through the system with minimal mocking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, Self, TypedDict

import pytest

from pollux.config import resolve_config
from pollux.config.core import FrozenConfig
from pollux.core.api_parts import TextPart
from pollux.core.api_plan import APICall, ExecutionPlan, UploadTask
from pollux.core.commands import InitialCommand, PlannedCommand, ResolvedCommand
from pollux.core.execution_options import ExecutionOptions, RemoteFilePolicy
from pollux.core.models import APITier
from pollux.core.types import APIPart, FilePlaceholder, FileRefPart, Source, Success
from pollux.executor import create_executor
from pollux.pipeline.adapters.base import (
    CachingCapability,
    GenerationAdapter,
    UploadsCapability,
)
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.cache_stage import CacheStage
from pollux.pipeline.registries import CacheRegistry, FileRegistry
from pollux.pipeline.remote_materialization import RemoteMaterializationStage

if TYPE_CHECKING:
    from collections.abc import Iterable
    import os
    from types import TracebackType

    from _pytest.monkeypatch import MonkeyPatch


# =============================================================================
# Integration: Full Pipeline Flow
# =============================================================================


@pytest.mark.integration
class TestPipelineIntegration:
    """End-to-end integration tests for the full pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_flow_end_to_end(self) -> None:
        """Verify data flows correctly through the entire pipeline.

        Uses 'google' provider to enable real planning/estimation logic, but relies on
        APIHandler's default `use_real_api=False` behavior to use the internal _MockAdapter
        for execution.
        """
        config = resolve_config(
            overrides={
                "provider": "google",
                "model": "gemini-2.0-flash",
                "api_key": "mock-key",
                "use_real_api": False,
            }
        )

        executor = create_executor(config)

        cmd = InitialCommand(
            sources=(
                Source.from_text("Context document 1", identifier="doc1"),
                Source.from_text("Context document 2", identifier="doc2"),
            ),
            prompts=("Analyze these documents",),
            config=config,
        )

        result_envelope = await executor.execute(cmd)

        assert result_envelope["status"] == "ok"
        assert isinstance(result_envelope["answers"], list)
        assert len(result_envelope["answers"]) == 1

        metrics = result_envelope.get("metrics", {})
        assert isinstance(metrics, dict)


# =============================================================================
# Unit: Cache Single-Flight
# =============================================================================


@dataclass
class _FakeCachingAdapter(GenerationAdapter, CachingCapability):
    """Fake adapter that tracks cache creation calls."""

    calls: int = 0

    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],
        system_instruction: str | None,
        ttl_seconds: int | None,
    ) -> str:
        _ = system_instruction, ttl_seconds
        self.calls += 1
        await asyncio.sleep(0.05)
        return f"cachedContents/test-{model_name}-{len(content_parts)}"

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:  # pragma: no cover - not used
        _ = api_parts, api_config
        return {"model": model_name}


@pytest.mark.unit
class TestCacheSingleFlight:
    """Cache creation must be single-flight to avoid duplicate API calls."""

    @pytest.mark.asyncio
    async def test_cache_creation_is_single_flight(self) -> None:
        """Concurrent cache requests for same content produce single API call."""
        # Exception: this is an interior-stage test because it guards a real
        # production failure mode (duplicate cache creation under concurrency).
        cfg = resolve_config(
            overrides={"use_real_api": True, "api_key": "x", "enable_caching": True}
        )

        initial = InitialCommand.strict(sources=(), prompts=("p",), config=cfg)
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        plan = ExecutionPlan(
            calls=(
                APICall(
                    model_name=cfg.model, api_parts=(TextPart("u"),), api_config={}
                ),
            ),
            shared_parts=(TextPart("shared"),),
        )
        command = PlannedCommand(resolved=resolved, execution_plan=plan)

        reg = CacheRegistry()
        adapter = _FakeCachingAdapter()
        stage = CacheStage(registries={"cache": reg}, adapter_factory=lambda _: adapter)

        r1, r2 = await asyncio.gather(stage.handle(command), stage.handle(command))
        assert isinstance(r1, Success) and isinstance(r2, Success)
        c1 = r1.value.execution_plan.calls[0].cache_name_to_use
        c2 = r2.value.execution_plan.calls[0].cache_name_to_use
        assert isinstance(c1, str) and c1 == c2
        assert adapter.calls == 1


# =============================================================================
# Unit: Upload Single-Flight and Indexing
# =============================================================================


class _UploadRef(TypedDict):
    uri: str
    mime_type: str | None


@dataclass
class _FakeUploadsAdapter(GenerationAdapter, UploadsCapability):
    """Fake adapter that tracks upload calls and captures prepared parts."""

    calls: int = 0
    last_parts: tuple[Any, ...] | None = None

    async def upload_file_local(
        self, path: str | os.PathLike[str], mime_type: str | None
    ) -> _UploadRef:
        self.calls += 1
        await asyncio.sleep(0.01)
        return {"uri": f"mock://{Path(path)}", "mime_type": mime_type}

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:
        _ = model_name, api_config
        self.last_parts = api_parts
        return {"text": "ok"}


@pytest.mark.unit
class TestUploadSingleFlight:
    """File uploads must be deduplicated to avoid redundant network calls."""

    @pytest.mark.asyncio
    async def test_upload_single_flight_for_same_file(self) -> None:
        """Multiple upload tasks for same file produce single upload call."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.txt"
            p.write_text("hello")

            call_parts: list[APIPart] = [
                FilePlaceholder(local_path=p, mime_type="text/plain", ephemeral=False),
                FilePlaceholder(local_path=p, mime_type="text/plain", ephemeral=False),
            ]
            tasks = (
                UploadTask(
                    part_index=0,
                    local_path=p,
                    mime_type="text/plain",
                    required=False,
                ),
                UploadTask(
                    part_index=1,
                    local_path=p,
                    mime_type="text/plain",
                    required=False,
                ),
            )

            adapter = _FakeUploadsAdapter()
            handler = APIHandler(registries={"files": FileRegistry()}, adapter=adapter)
            cmd = _mk_cmd(shared_parts=(), call_parts=call_parts)
            cmd = PlannedCommand(
                resolved=cmd.resolved,
                execution_plan=ExecutionPlan(
                    calls=cmd.execution_plan.calls,
                    shared_parts=cmd.execution_plan.shared_parts,
                    upload_tasks=tasks,
                ),
            )

            result = await handler.handle(cmd)
            assert isinstance(result, Success)
            assert adapter.calls == 1
            assert adapter.last_parts is not None
            assert len(adapter.last_parts) == 2
            assert isinstance(adapter.last_parts[0], FileRefPart)
            assert isinstance(adapter.last_parts[1], FileRefPart)


@pytest.mark.unit
class TestUploadTaskIndexing:
    """Upload task indices must map correctly between per-call and combined parts."""

    @pytest.mark.asyncio
    async def test_upload_task_indices_are_relative_to_call_parts(self) -> None:
        """Upload task index 1 in per-call parts maps to correct combined index."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.txt"
            p.write_text("hello")

            shared: list[APIPart] = [TextPart("shared")]
            call_parts: list[APIPart] = [
                TextPart("prompt"),
                FilePlaceholder(local_path=p, mime_type="text/plain", ephemeral=False),
            ]
            tasks = (
                UploadTask(
                    part_index=1, local_path=p, mime_type="text/plain", required=True
                ),
            )

            adapter = _FakeUploadsAdapter()
            handler = APIHandler(adapter=adapter)
            cmd = _mk_cmd(shared_parts=shared, call_parts=call_parts)
            cmd = PlannedCommand(
                resolved=cmd.resolved,
                execution_plan=ExecutionPlan(
                    calls=cmd.execution_plan.calls,
                    shared_parts=cmd.execution_plan.shared_parts,
                    upload_tasks=tasks,
                ),
            )

            result = await handler.handle(cmd)
            assert isinstance(result, Success)
            assert adapter.last_parts is not None
            assert isinstance(adapter.last_parts[2], FileRefPart)
            assert isinstance(adapter.last_parts[1], TextPart)
            assert adapter.calls == 1


# =============================================================================
# Unit: Remote Materialization
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_async_tasks():
    """Clean up any lingering async tasks after each test."""
    yield
    try:
        loop = asyncio.get_running_loop()
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            get_name = getattr(task, "get_name", None)
            name = get_name() if callable(get_name) else ""
            if isinstance(name, str) and name.startswith("remote_materialization"):
                task.cancel()
    except RuntimeError:
        pass


def _cfg() -> FrozenConfig:
    return FrozenConfig(
        model="test-model",
        api_key=None,
        use_real_api=False,
        enable_caching=False,
        ttl_seconds=0,
        telemetry_enabled=False,
        tier=APITier.FREE,
        provider="gemini",
        extra={},
        request_concurrency=1,
    )


class _FakeResp:
    def __init__(
        self, data: bytes, content_type: str = "application/pdf", url: str | None = None
    ) -> None:
        self._data: bytes = data
        self._ptr: int = 0
        self.headers: dict[str, str] = {"Content-Type": content_type}
        self._url = url or "https://host/file.pdf"

    def read(self, n: int) -> bytes:
        if self._ptr >= len(self._data):
            return b""
        chunk = self._data[self._ptr : self._ptr + n]
        self._ptr += len(chunk)
        return chunk

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def geturl(self) -> str:
        return self._url


def _mk_cmd(
    shared_parts: Iterable[APIPart] = (), call_parts: Iterable[APIPart] = ()
) -> PlannedCommand:
    init = InitialCommand.strict(
        sources=(), prompts=("p",), config=_cfg(), options=None
    )
    res = ResolvedCommand(initial=init, resolved_sources=())
    call = APICall(model_name="m", api_parts=tuple(call_parts), api_config={})
    plan = ExecutionPlan(calls=(call,), shared_parts=tuple(shared_parts))
    return PlannedCommand(resolved=res, execution_plan=plan)


@pytest.mark.unit
class TestRemoteMaterialization:
    """Remote file materialization behavior and edge cases."""

    @pytest.mark.asyncio
    async def test_noop_when_disabled(self) -> None:
        """Stage is no-op when remote file policy is disabled."""
        cmd = _mk_cmd(
            shared_parts=(
                FileRefPart(uri="https://x/y.pdf", mime_type="application/pdf"),
            )
        )
        stage = RemoteMaterializationStage()
        out = await stage.handle(cmd)
        assert isinstance(out, Success)
        sp0 = out.value.execution_plan.shared_parts[0]
        assert isinstance(sp0, FileRefPart)
        assert sp0.uri == "https://x/y.pdf"

    @pytest.mark.asyncio
    async def test_shared_pdf_promotion(self, monkeypatch: MonkeyPatch) -> None:
        """Remote PDF in shared_parts is downloaded and replaced with local placeholder."""

        class _Counter:
            count: int = 0
            last_url: str | None = None

        c = _Counter()

        def fake_urlopen(_req, timeout=None):
            _ = timeout
            c.count += 1
            url = getattr(_req, "full_url", _req)
            c.last_url = str(url)
            return _FakeResp(b"%PDF-1.4\n...")

        with monkeypatch.context() as m:
            m.setattr("urllib.request.urlopen", fake_urlopen)
            policy = RemoteFilePolicy(enabled=True)
            cmd = _mk_cmd(
                shared_parts=(
                    FileRefPart(
                        uri="https://host/file.pdf", mime_type="application/pdf"
                    ),
                )
            )
            cmd = PlannedCommand(
                resolved=ResolvedCommand(
                    initial=InitialCommand.strict(
                        sources=(),
                        prompts=("p",),
                        config=_cfg(),
                        options=ExecutionOptions(remote_files=policy),
                    ),
                    resolved_sources=(),
                ),
                execution_plan=cmd.execution_plan,
            )
            stage = RemoteMaterializationStage()
            out = await stage.handle(cmd)
            assert isinstance(out, Success)
            new_shared = out.value.execution_plan.shared_parts
            fp = new_shared[0]
            assert hasattr(fp, "local_path")
            assert getattr(fp, "ephemeral", False) is True
            assert Path(fp.local_path).exists()
            assert c.count == 1

    @pytest.mark.asyncio
    async def test_per_call_promotion_and_dedup(self, monkeypatch: MonkeyPatch) -> None:
        """Same URL in shared and per-call parts downloads only once."""
        count = {"n": 0}

        def fake_urlopen(_req, timeout=None):
            _ = timeout
            count["n"] += 1
            return _FakeResp(b"%PDF-1.4\n...")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        policy = RemoteFilePolicy(enabled=True)
        shared = FileRefPart(uri="https://host/same.pdf", mime_type="application/pdf")
        per_call = FileRefPart(uri="https://host/same.pdf", mime_type="application/pdf")
        cmd = _mk_cmd(shared_parts=(shared,), call_parts=(per_call,))
        cmd = PlannedCommand(
            resolved=ResolvedCommand(
                initial=InitialCommand.strict(
                    sources=(),
                    prompts=("p",),
                    config=_cfg(),
                    options=ExecutionOptions(remote_files=policy),
                ),
                resolved_sources=(),
            ),
            execution_plan=cmd.execution_plan,
        )
        stage = RemoteMaterializationStage()
        out = await stage.handle(cmd)
        assert isinstance(out, Success)
        assert count["n"] == 1
        new_plan = out.value.execution_plan
        assert hasattr(new_plan.shared_parts[0], "local_path")
        assert hasattr(new_plan.calls[0].api_parts[0], "local_path")

    @pytest.mark.asyncio
    async def test_size_limit_enforced_skip(self, monkeypatch: MonkeyPatch) -> None:
        """Files exceeding size limit are skipped when on_error='skip'."""

        def fake_urlopen(_req, timeout=None):
            _ = timeout
            return _FakeResp(b"x" * (30 * 1024 * 1024))

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        policy = RemoteFilePolicy(
            enabled=True, max_bytes=1 * 1024 * 1024, on_error="skip"
        )
        ref = FileRefPart(uri="https://host/big.pdf", mime_type="application/pdf")
        cmd = _mk_cmd(shared_parts=(ref,))
        cmd = PlannedCommand(
            resolved=ResolvedCommand(
                initial=InitialCommand.strict(
                    sources=(),
                    prompts=("p",),
                    config=_cfg(),
                    options=ExecutionOptions(remote_files=policy),
                ),
                resolved_sources=(),
            ),
            execution_plan=cmd.execution_plan,
        )
        stage = RemoteMaterializationStage()
        out = await stage.handle(cmd)
        assert isinstance(out, Success)
        sp0 = out.value.execution_plan.shared_parts[0]
        assert hasattr(sp0, "uri") and not hasattr(sp0, "local_path")

    @pytest.mark.asyncio
    async def test_http_rejected_by_default_and_allowed_when_enabled(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """HTTP URLs are rejected by default, allowed with allow_http=True."""

        def fake_urlopen(_req, timeout=None):
            _ = timeout
            return _FakeResp(b"%PDF-1.4\n...", url="http://host/file.pdf")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        ref = FileRefPart(uri="http://host/file.pdf", mime_type="application/pdf")
        cmd = _mk_cmd(shared_parts=(ref,))
        cmd = PlannedCommand(
            resolved=ResolvedCommand(
                initial=InitialCommand.strict(
                    sources=(),
                    prompts=("p",),
                    config=_cfg(),
                    options=ExecutionOptions(
                        remote_files=RemoteFilePolicy(enabled=True)
                    ),
                ),
                resolved_sources=(),
            ),
            execution_plan=cmd.execution_plan,
        )
        stage = RemoteMaterializationStage()
        out = await stage.handle(cmd)
        assert isinstance(out, Success)
        sp0 = out.value.execution_plan.shared_parts[0]
        assert isinstance(sp0, FileRefPart)

        # Allowed when allow_http=True
        cmd2 = PlannedCommand(
            resolved=ResolvedCommand(
                initial=InitialCommand.strict(
                    sources=(),
                    prompts=("p",),
                    config=_cfg(),
                    options=ExecutionOptions(
                        remote_files=RemoteFilePolicy(enabled=True, allow_http=True)
                    ),
                ),
                resolved_sources=(),
            ),
            execution_plan=cmd.execution_plan,
        )
        out2 = await stage.handle(cmd2)
        assert isinstance(out2, Success)
        fp = out2.value.execution_plan.shared_parts[0]
        assert hasattr(fp, "local_path") and getattr(fp, "ephemeral", False)
