from typing import Any

import pytest

from pollux.config.core import FrozenConfig
from pollux.core.exceptions import (
    InvariantViolationError,
    PolluxError,
)
from pollux.core.models import APITier
from pollux.core.types import InitialCommand, Result, Success
from pollux.executor import GeminiExecutor
from pollux.pipeline.base import BaseAsyncHandler


class PassThroughStage(BaseAsyncHandler[Any, Any, PolluxError]):
    """A minimal handler that returns the input unchanged, violating the final envelope invariant."""

    async def handle(self, command: Any) -> Result[Any, PolluxError]:
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


@pytest.mark.contract
@pytest.mark.asyncio
async def test_invariant_violation_when_no_result_envelope_produced() -> None:
    # A single pass-through stage leaves the executor with a non-dict state
    executor = GeminiExecutor(_minimal_config(), pipeline_handlers=[PassThroughStage()])

    with pytest.raises(InvariantViolationError) as ei:
        await executor.execute(_minimal_command())

    assert "ResultEnvelope" in str(ei.value)
    # Stage name recorded on the invariant error should be the final stage
    assert getattr(ei.value, "stage_name", None) == "PassThroughStage"
