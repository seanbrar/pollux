import pytest

from pollux.config import resolve_config
from pollux.core.sources import Source
from pollux.core.types import InitialCommand
from pollux.executor import create_executor

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_minimal_pipeline_happy_path():
    executor = create_executor(
        resolve_config(overrides={"api_key": "test", "model": "gemini-2.0-flash"})
    )
    cmd = InitialCommand(
        sources=(Source.from_text("hello world"),),
        prompts=("Echo me",),
        config=executor.config,
    )

    result = await executor.execute(cmd)

    assert result["status"] == "ok"
    assert isinstance(result["answers"], list)
    assert result["answers"] and "echo:" in result["answers"][0]


@pytest.mark.asyncio
async def test_source_from_file_raises_on_missing_path():
    create_executor(
        resolve_config(overrides={"api_key": "test", "model": "gemini-2.0-flash"})
    )
    # Non-existent path now raises during Source construction (explicit/strict API)
    with pytest.raises(ValueError):
        _ = Source.from_file("/definitely/not/here.xyz")
