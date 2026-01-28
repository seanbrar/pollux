from typing import Any

import pytest

from pollux.config.core import FrozenConfig
from pollux.core.exceptions import (
    PipelineError,
    PolluxError,
)
from pollux.core.models import APITier
from pollux.core.types import Failure, InitialCommand, Result, Success
from pollux.executor import GeminiExecutor
from pollux.pipeline.base import BaseAsyncHandler


class FailingStage(BaseAsyncHandler[Any, Any, PolluxError]):
    """A minimal handler that always fails to exercise PipelineError path."""

    async def handle(
        self, _command: Any
    ) -> Result[Any, PolluxError]:  # pragma: no cover - signature exercised by executor
        return Failure(PolluxError("boom"))


class PassThroughStage(BaseAsyncHandler[Any, Any, PolluxError]):
    """A minimal handler that returns the input unchanged, violating the final envelope invariant."""

    async def handle(
        self, command: Any
    ) -> Result[Any, PolluxError]:  # pragma: no cover - signature exercised by executor
        return Success(command)


def _minimal_config() -> FrozenConfig:
    return FrozenConfig(
        model="gemini-2.0-flash",
        api_key=None,
        use_real_api=False,
        enable_caching=False,
        ttl_seconds=0,
        telemetry_enabled=False,
        tier=APITier.FREE,
        provider="gemini",
        extra={},
        request_concurrency=6,
    )


def _minimal_command(cfg: FrozenConfig | None = None) -> InitialCommand:
    return InitialCommand(
        sources=(), prompts=("Hello",), config=cfg or _minimal_config()
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_error_uses_true_stage_name() -> None:
    executor = GeminiExecutor(_minimal_config(), pipeline_handlers=[FailingStage()])

    with pytest.raises(PipelineError) as ei:
        await executor.execute(_minimal_command())

    err = ei.value
    # Stage name should reflect the inner stage, not the erased wrapper
    assert err.handler_name == "FailingStage"
    # Convenience check: stage_names property exposes correct names
    assert executor.stage_names == ("FailingStage",)


@pytest.mark.unit
def test_erase_guard_raises_for_invalid_handler() -> None:
    # Creating an executor with an invalid handler (no 'handle') should raise TypeError during erase()
    with pytest.raises(TypeError):
        GeminiExecutor(_minimal_config(), pipeline_handlers=[object()])  # type: ignore
