import pytest

from pollux.config import resolve_config
from pollux.core.sources import Source
from pollux.core.types import InitialCommand
from pollux.executor import create_executor

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_final_result_includes_token_validation_metrics():
    executor = create_executor(
        resolve_config(overrides={"api_key": "k", "model": "gemini-2.0-flash"})
    )
    cmd = InitialCommand(
        sources=(Source.from_text("hello world"),),
        prompts=("Echo me",),
        config=executor.config,
    )

    result = await executor.execute(cmd)

    assert result.get("status") == "ok"
    metrics = result.get("metrics")
    assert isinstance(metrics, dict)
    tv = metrics.get("token_validation")
    assert isinstance(tv, dict)
    # Basic shape checks
    for key in (
        "estimated_expected",
        "estimated_min",
        "estimated_max",
        "actual",
        "in_range",
    ):
        assert key in tv
    assert isinstance(tv["actual"], int)
    assert isinstance(tv["in_range"], bool)
