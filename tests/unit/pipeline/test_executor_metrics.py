import pytest

from pollux.config import resolve_config
from pollux.core.sources import Source
from pollux.core.types import InitialCommand
from pollux.executor import create_executor


@pytest.mark.asyncio
async def test_executor_surfaces_all_stage_durations():
    executor = create_executor(resolve_config(overrides={"api_key": "k"}))
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "k"}),
    )

    result = await executor.execute(initial)

    assert result["status"] == "ok"
    metrics = result.get("metrics", {})
    assert isinstance(metrics, dict)
    durations = metrics.get("durations")
    assert isinstance(durations, dict)
    # Expect all stages to be present:
    for stage in ("SourceHandler", "ExecutionPlanner", "APIHandler", "ResultBuilder"):
        assert stage in durations
