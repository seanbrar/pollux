import asyncio
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType
from typing import Self

from _pytest.monkeypatch import MonkeyPatch
import pytest

from pollux.config.core import FrozenConfig
from pollux.core.api_plan import APICall, ExecutionPlan
from pollux.core.commands import InitialCommand, PlannedCommand, ResolvedCommand
from pollux.core.execution_options import ExecutionOptions, RemoteFilePolicy
from pollux.core.models import APITier
from pollux.core.types import APIPart, FileRefPart, Success
from pollux.pipeline.remote_materialization import RemoteMaterializationStage


@pytest.fixture(autouse=True)
def cleanup_async_tasks():
    """Clean up any lingering async tasks after each test."""
    yield
    # Give any pending async tasks a chance to complete
    try:
        loop = asyncio.get_running_loop()
        # Cancel any pending tasks created by remote materialization
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            get_name = getattr(task, "get_name", None)
            name = get_name() if callable(get_name) else ""
            if isinstance(name, str) and name.startswith("remote_materialization"):
                task.cancel()
    except RuntimeError:
        # No running loop
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


@pytest.mark.asyncio
async def test_noop_when_disabled() -> None:
    cmd = _mk_cmd(
        shared_parts=(FileRefPart(uri="https://x/y.pdf", mime_type="application/pdf"),)
    )
    stage = RemoteMaterializationStage()
    out = await stage.handle(cmd)
    assert isinstance(out, Success)
    sp0 = out.value.execution_plan.shared_parts[0]
    assert isinstance(sp0, FileRefPart)
    assert sp0.uri == "https://x/y.pdf"


@pytest.mark.asyncio
async def test_shared_pdf_promotion(monkeypatch: MonkeyPatch) -> None:
    # Patch urlopen to return a small PDF-like payload

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

    # Use context manager to ensure proper cleanup
    with monkeypatch.context() as m:
        m.setattr("urllib.request.urlopen", fake_urlopen)
        policy = RemoteFilePolicy(enabled=True)
        cmd = _mk_cmd(
            shared_parts=(
                FileRefPart(uri="https://host/file.pdf", mime_type="application/pdf"),
            )
        )
        # Inject options
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
        # The stage should replace FileRefPart with FilePlaceholder (duck by attrs)
        fp = new_shared[0]
        assert hasattr(fp, "local_path")
        assert getattr(fp, "ephemeral", False) is True
        assert Path(fp.local_path).exists()
        assert c.count == 1


@pytest.mark.asyncio
async def test_arxiv_abs_canonicalization(monkeypatch: MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {"urls": []}

    def fake_urlopen(_req, timeout=None):
        _ = timeout
        url = getattr(_req, "full_url", _req)
        seen["urls"].append(str(url))
        return _FakeResp(b"%PDF-1.4\n...")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    policy = RemoteFilePolicy(enabled=True)
    cmd = _mk_cmd(
        shared_parts=(
            FileRefPart(uri="https://arxiv.org/abs/1234.56789v2", mime_type=None),
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
    assert any(
        u.endswith("/pdf/1234.56789v2.pdf") for u in seen["urls"]
    )  # canonicalized


@pytest.mark.asyncio
async def test_per_call_promotion_and_dedup(monkeypatch: MonkeyPatch) -> None:
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
    # Dedup: one download for same URL across shared + per-call
    assert count["n"] == 1
    # Replacement occurred in both locations
    new_plan = out.value.execution_plan
    assert hasattr(new_plan.shared_parts[0], "local_path")
    assert hasattr(new_plan.calls[0].api_parts[0], "local_path")


@pytest.mark.asyncio
async def test_size_limit_enforced_skip(monkeypatch: MonkeyPatch) -> None:
    def fake_urlopen(_req, timeout=None):
        _ = timeout
        # 30MB payload in chunks
        return _FakeResp(b"x" * (30 * 1024 * 1024))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    policy = RemoteFilePolicy(enabled=True, max_bytes=1 * 1024 * 1024, on_error="skip")
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
    # On skip: original FileRefPart remains (not replaced with placeholder)
    sp0 = out.value.execution_plan.shared_parts[0]
    assert hasattr(sp0, "uri") and not hasattr(sp0, "local_path")


@pytest.mark.asyncio
async def test_http_rejected_by_default_and_allowed_when_enabled(
    monkeypatch: MonkeyPatch,
) -> None:
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
                options=ExecutionOptions(remote_files=RemoteFilePolicy(enabled=True)),
            ),
            resolved_sources=(),
        ),
        execution_plan=cmd.execution_plan,
    )
    stage = RemoteMaterializationStage()
    out = await stage.handle(cmd)
    # HTTP is not allowed by default: stage is a no-op (Success, no replacement)
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


@pytest.mark.asyncio
async def test_content_type_mismatch_skip(monkeypatch: MonkeyPatch) -> None:
    # Content-Type mismatch should be skipped when on_error='skip'
    def fake_urlopen(_req, timeout=None):
        _ = timeout
        return _FakeResp(b"<html>not pdf</html>", content_type="text/html")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    policy = RemoteFilePolicy(enabled=True, on_error="skip")
    ref = FileRefPart(uri="https://host/file.pdf", mime_type=None)
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
    # Original part remains since it was skipped
    sp0 = out.value.execution_plan.shared_parts[0]
    assert isinstance(sp0, FileRefPart) and sp0.uri == "https://host/file.pdf"


@pytest.mark.asyncio
async def test_redirect_to_non_http_scheme_skip(monkeypatch: MonkeyPatch) -> None:
    # Final URL resolves to file:// (non-http[s]) → should be skipped when on_error='skip'
    def fake_urlopen(_req, timeout=None):  # noqa: ARG001
        return _FakeResp(b"%PDF-1.4\n...", url="file://evil")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    policy = RemoteFilePolicy(enabled=True, on_error="skip")
    ref = FileRefPart(uri="https://host/looks-ok.pdf", mime_type="application/pdf")
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
    assert isinstance(sp0, FileRefPart) and sp0.uri == "https://host/looks-ok.pdf"


@pytest.mark.asyncio
async def test_redirect_to_non_http_scheme_fail(monkeypatch: MonkeyPatch) -> None:
    # Final URL resolves to file:// (non-http[s]) → failure when on_error='fail'
    def fake_urlopen(_req, timeout=None):  # noqa: ARG001
        return _FakeResp(b"%PDF-1.4\n...", url="file://evil")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    policy = RemoteFilePolicy(enabled=True, on_error="fail")
    ref = FileRefPart(uri="https://host/looks-ok.pdf", mime_type="application/pdf")
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
    # Import within block to avoid unused import outside this test
    from pollux.core.types import Failure as _Failure

    assert isinstance(out, _Failure)
