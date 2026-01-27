import asyncio
from typing import Any
from pollux.executor import GeminiExecutor
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.source_handler import SourceHandler
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.adapters.base import GenerationAdapter
from pollux.config import resolve_config
from pollux.core.types import InitialCommand

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
            "text": f"OpenAI Response for model {model_name}",
            "usage": {"total_token_count": 42}
        }

async def main():
    # 1. Setup config
    config = resolve_config(overrides={"model": "gpt-4o", "use_real_api": True, "api_key": "dummy-key"})
    
    # 2. Build custom pipeline with our MockOpenAIAdapter
    handlers = [
        SourceHandler(),
        ExecutionPlanner(),
        APIHandler(adapter=MockOpenAIAdapter()),
        ResultBuilder()
    ]
    
    # 3. Initialize Executor
    executor = GeminiExecutor(config, pipeline_handlers=handlers)
    
    # 4. Run a simple command
    cmd = InitialCommand.strict(
        sources=(),
        prompts=("Hello from custom adapter!",),
        config=config
    )
    
    result = await executor.execute(cmd)
    
    print("\n--- Verification Result ---")
    print(f"Status: {result['status']}")
    print(f"Answers: {result['answers']}")
    print(f"Usage: {result['usage']}")
    
    # Check if the response matches our mock
    if "OpenAI Response" in str(result['answers']):
        print("\nSUCCESS: Custom provider injection verified!")
    else:
        print("\nFAILURE: Response does not match mock adapter.")

if __name__ == "__main__":
    asyncio.run(main())
