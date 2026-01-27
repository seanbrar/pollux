from __future__ import annotations

import asyncio
import logging
from typing import Any

from pollux.config import resolve_config
from pollux.core.types import InitialCommand
from pollux.executor import GeminiExecutor
from pollux.pipeline.adapters.base import GenerationAdapter
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.source_handler import SourceHandler

logger = logging.getLogger(__name__)


class MockOpenAIAdapter(GenerationAdapter):
    """A mock adapter that simulates an OpenAI-style response."""

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:
        return {
            "text": (
                f"OpenAI Response for model {model_name}. "
                f"Received {len(api_parts)} parts and config with keys: {sorted(api_config.keys())}"
            ),
            "usage": {"total_token_count": 42},
        }


async def main() -> None:
    # 1. Setup config
    config = resolve_config(
        overrides={"model": "gpt-4o", "use_real_api": True, "api_key": "dummy-key"}
    )

    # 2. Build custom pipeline with our MockOpenAIAdapter
    handlers: list[Any] = [
        SourceHandler(),
        ExecutionPlanner(),
        APIHandler(adapter=MockOpenAIAdapter()),
        ResultBuilder(),
    ]

    # 3. Initialize Executor
    executor = GeminiExecutor(config, pipeline_handlers=handlers)

    # 4. Run a simple command
    cmd = InitialCommand.strict(
        sources=(), prompts=("Hello from custom adapter!",), config=config
    )

    result = await executor.execute(cmd)

    logger.info("Verification Result Status: %s", result["status"])
    logger.info("Verification Result Answers: %s", result["answers"])
    logger.info("Verification Result Usage: %s", result["usage"])

    # Check if the response matches our mock
    assert "OpenAI Response" in str(result["answers"]), (
        "FAILURE: Response does not match mock adapter."
    )
    logger.info("SUCCESS: Custom provider injection verified!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
