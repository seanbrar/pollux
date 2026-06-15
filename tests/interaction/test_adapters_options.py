"""Unit tests: v1 ``Options`` decomposes cleanly into the v2 split.

The adapters here are transitional, but the decomposition they demonstrate is
the load-bearing v2 reshaping of the ``Options`` kitchen-sink into ``Environment``
/ ``Input`` / ``OutputRequirements``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pollux.continuation import ConversationState
from pollux.interaction.adapters import (
    continuation_from_state,
    environment_from_options,
    input_from_options,
    requirements_from_options,
    state_from_continuation,
)
from pollux.options import Options
from pollux.source import Source

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

pytestmark = pytest.mark.unit


def test_requirements_projection():
    opts = Options(temperature=0.0, max_tokens=512, tool_choice="auto", top_p=0.9)
    req = requirements_from_options(opts)
    assert req.temperature == 0.0
    assert req.max_tokens == 512
    assert req.top_p == 0.9
    assert req.tool_choice == "auto"


def test_environment_projection():
    opts = Options(
        system_instruction="sys",
        tools=[{"name": "f", "description": "d", "parameters": {"type": "object"}}],
    )
    env = environment_from_options(opts, [Source.from_text("doc")])
    assert env.instructions == "sys"
    assert len(env.sources) == 1
    assert env.tools[0].name == "f"


def test_input_projection_with_plain_prompt():
    inp = input_from_options(Options(), "the prompt")
    assert inp.content == "the prompt"
    assert inp.continuation is None
    assert inp.history is None


def test_input_projection_recovers_continuation():
    state = ConversationState(
        history=[{"role": "user", "content": "earlier"}],
        response_id="r1",
        provider="anthropic",
    )
    envelope: ResultEnvelope = {"_conversation_state": state.to_dict()}
    inp = input_from_options(Options(continue_from=envelope), "next")
    assert inp.continuation is not None
    assert inp.continuation.response_id == "r1"


def test_continuation_state_roundtrip_preserves_messages():
    state = ConversationState(
        history=[
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "1", "name": "f", "arguments": '{"a": 1}'}],
            },
        ],
        response_id="r1",
        provider="gemini",
    )
    cont = continuation_from_state(state)
    assert cont.response_id == "r1"
    assert cont.provider == "gemini"
    assert cont.messages[1].tool_calls[0].name == "f"
    assert cont.messages[1].tool_calls[0].arguments == {"a": 1}

    back = state_from_continuation(cont)
    assert back.history[0]["content"] == "hi"
    assert back.history[1]["tool_calls"][0]["arguments"] == '{"a": 1}'
