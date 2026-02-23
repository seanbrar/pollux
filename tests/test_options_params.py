import pytest

from pollux import Config, Options, run


def test_temperature_and_top_p() -> None:
    # Ensure options accept generation params
    opts = Options(temperature=0.7, top_p=0.9)
    assert opts.temperature == 0.7
    assert opts.top_p == 0.9


def test_tools_and_tool_choice() -> None:
    # Ensure options accept tool params
    tools = [
        {
            "name": "get_weather",
            "description": "Get the weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
            },
        }
    ]
    opts = Options(tools=tools, tool_choice="auto")
    assert opts.tools == tools
    assert opts.tool_choice == "auto"


@pytest.mark.asyncio
async def test_mock_generate_with_options() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite", use_mock=True)
    opts = Options(
        temperature=0.5,
        top_p=0.5,
        tools=[{"name": "test_tool"}],
        tool_choice="auto",
    )
    result = await run("Hello world!", config=config, options=opts)
    # Mock just returns the prompt but shouldn't crash
    assert "echo: Hello world!" in result["answers"][0]


def test_history_with_none_content_accepted() -> None:
    """Assistant messages with content: None pass validation (tool-call pattern)."""
    opts = Options(
        history=[
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
        ]
    )
    assert opts.history is not None
    assert opts.history[0]["content"] is None
