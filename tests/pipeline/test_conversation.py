"""Pipeline boundary tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

import pollux
import pollux.cache
from pollux.config import Config
from pollux.continuation import ConversationState
from pollux.errors import (
    ConfigurationError,
)
from pollux.options import Options
from pollux.providers.base import (
    ProviderCapabilities,
)
from pollux.providers.models import (
    Message,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)
from pollux.source import Source
from tests.conftest import (
    GEMINI_MODEL,
    LOCAL_MODEL,
    FakeProvider,
)
from tests.helpers import CaptureProvider as KwargsCaptureProvider

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

pytestmark = pytest.mark.integration


# =============================================================================
# Conversation & Tool-Call Transparency (v1.1-v1.2)
#
# MTMT complexity marker: this cluster is dense (~12 tests) because
# conversation has multiple interacting facets — history forwarding,
# continue_from, tool-call preservation, and state emission.  Each test
# covers a distinct boundary, but if this section keeps growing it may
# signal that the conversation surface should be split out into its own
# boundary file or simplified at the design level.
# =============================================================================


@pytest.mark.asyncio
async def test_conversation_options_are_forwarded_when_provider_supports_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation options should pass through when provider supports the feature."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    await pollux.run_many(
        ("Q1?",),
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )
    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["history"] == [
        Message(role="user", content="hello")
    ]


@pytest.mark.asyncio
async def test_conversation_requires_single_prompt_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation continuity is single-turn per API call in v1.1."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="exactly one prompt"):
        await pollux.run_many(
            ("Q1?", "Q2?"),
            config=cfg,
            options=Options(history=[{"role": "user", "content": "hello"}]),
        )


@pytest.mark.asyncio
async def test_continue_from_requires_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continue_from must include _conversation_state; valid state is forwarded."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="missing _conversation_state"):
        await pollux.run_many(
            ("Q1?",),
            config=cfg,
            options=Options(continue_from={"status": "ok", "answers": ["x"]}),
        )

    previous: ResultEnvelope = {
        "status": "ok",
        "answers": ["x"],
        "_conversation_state": {
            "history": [{"role": "user", "content": "hello"}],
            "response_id": "resp_123",
        },
    }
    await pollux.run_many(
        ("Next?",),
        config=cfg,
        options=Options(continue_from=previous),
    )

    assert len(fake.generate_kwargs) == 1
    assert fake.generate_kwargs[0]["request"].history == [
        Message(role="user", content="hello")
    ]
    assert fake.generate_kwargs[0]["request"].previous_response_id == "resp_123"


@pytest.mark.asyncio
async def test_conversation_result_includes_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation runs should emit continuation state in the result envelope."""

    @dataclass
    class _ConversationProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=False,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="Assistant reply.",
                usage={"total_tokens": 1},
                response_id="resp_next",
            )

    fake = _ConversationProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "Next question?",
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    state = result.get("_conversation_state")
    assert isinstance(state, dict)
    assert state["response_id"] == "resp_next"
    # Forward-compat stamp: a future major can detect/reject incompatible state.
    assert state["version"] == 1
    assert state["provider"] == "gemini"
    assert state["history"] == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "Next question?"},
        {"role": "assistant", "content": "Assistant reply."},
    ]


def test_conversation_state_stamp_roundtrip_and_back_compat() -> None:
    """to_dict stamps version/provider; from_state_dict reads pre-1.8 state."""
    # Newly built state carries the schema version and provider marker.
    written = ConversationState(
        history=[{"role": "user", "content": "hi"}],
        provider="gemini",
    ).to_dict()
    assert written["version"] == ConversationState.SCHEMA_VERSION
    assert written["provider"] == "gemini"
    assert ConversationState.from_state_dict(written).provider == "gemini"

    # A pre-1.8 envelope (no version, no provider) still loads, read as v1.
    legacy = ConversationState.from_state_dict(
        {"history": [{"role": "user", "content": "hi"}]}
    )
    assert legacy.version == 1
    assert legacy.provider is None

    # provider is omitted from the dict when unset, keeping the shape compact.
    assert "provider" not in ConversationState(history=[]).to_dict()


@pytest.mark.asyncio
async def test_conversation_state_preserves_text_source_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text sources should remain in replayed history for local continuations."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False,
            uploads=False,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="local", model=LOCAL_MODEL, use_mock=True)

    first = await pollux.run(
        "What is the project code?",
        source=Source.from_text("The project code is K9-ORBIT."),
        config=cfg,
        options=Options(history=[]),
    )

    state = first.get("_conversation_state")
    assert isinstance(state, dict)
    assert state["history"][0] == {
        "role": "user",
        "content": "The project code is K9-ORBIT.\n\nWhat is the project code?",
    }

    await pollux.run(
        "Repeat it.",
        config=cfg,
        options=Options(continue_from=first),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["history"][0] == Message(
        role="user",
        content="The project code is K9-ORBIT.\n\nWhat is the project code?",
    )


@pytest.mark.asyncio
async def test_conversation_state_preserves_provider_state_from_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider response state should be persisted for continue_from loops."""

    @dataclass
    class _ProviderStateConversationProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=True,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="Assistant reply.",
                usage={"total_tokens": 1},
                provider_state={"anthropic_thinking_blocks": [{"type": "thinking"}]},
            )

    fake = _ProviderStateConversationProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="anthropic", model="claude-haiku-4-5", use_mock=True)

    result = await pollux.run(
        "Next question?",
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    state = result.get("_conversation_state")
    assert isinstance(state, dict)
    assert state["provider_state"] == {
        "anthropic_thinking_blocks": [{"type": "thinking"}]
    }
    assistant = state["history"][-1]
    assert assistant["provider_state"] == {
        "anthropic_thinking_blocks": [{"type": "thinking"}]
    }


def test_history_accepts_tool_messages() -> None:
    """Options(history=...) with tool-shaped messages should not raise."""
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "name": "get_weather", "arguments": '{"loc": "NYC"}'}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 72}'},
    ]
    opts = Options(history=history)
    assert opts.history == history


def test_history_still_rejects_items_without_role() -> None:
    """Items missing 'role' must still raise ConfigurationError."""
    with pytest.raises(ConfigurationError, match="role"):
        Options(history=[{"content": "no role here"}])


@pytest.mark.asyncio
async def test_tool_call_response_populates_conversation_state_without_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run() without history/continue_from must still populate _conversation_state
    when the response contains tool calls, so continue_tool can work."""

    @dataclass
    class _ToolCallProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=False,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="call_1", name="pick_color", arguments='{"color":"red"}'
                    )
                ],
                response_id="resp_abc",
            )

    fake = _ToolCallProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    # No history, no continue_from — just tools
    result = await pollux.run(
        "Pick a color.",
        config=cfg,
        options=Options(tools=[{"name": "pick_color"}]),
    )

    # _conversation_state must be present and usable
    state = result.get("_conversation_state")
    assert isinstance(state, dict), (
        "_conversation_state should be populated for tool-call responses"
    )
    assert "history" in state
    assert state["history"][-1]["role"] == "assistant"
    assert state["history"][-1]["tool_calls"] == [
        {"id": "call_1", "name": "pick_color", "arguments": '{"color":"red"}'}
    ]
    assert state.get("response_id") == "resp_abc"

    # The result should also have the tool_calls in the envelope
    assert result.get("tool_calls") == [
        [{"id": "call_1", "name": "pick_color", "arguments": '{"color":"red"}'}]
    ]


@pytest.mark.asyncio
async def test_tool_calls_preserved_in_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When provider returns tool_calls, conversation state preserves them."""

    @dataclass
    class _ToolCallProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=False,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="",
                tool_calls=[ToolCall(id="call_1", name="get_weather", arguments="{}")],
            )

    fake = _ToolCallProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "What's the weather?",
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    state = result.get("_conversation_state")
    assert isinstance(state, dict)
    last_msg = state["history"][-1]
    assert last_msg["role"] == "assistant"
    assert last_msg["tool_calls"] == [
        {"id": "call_1", "name": "get_weather", "arguments": "{}"}
    ]


@pytest.mark.asyncio
async def test_continue_from_preserves_tool_history_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continue_from with tool messages in history passes them to provider."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    tool_history: list[dict[str, Any]] = [
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "name": "get_weather", "arguments": "{}"}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 72}'},
    ]
    previous: ResultEnvelope = {
        "status": "ok",
        "answers": [""],
        "_conversation_state": {"history": tool_history},
    }

    await pollux.run(
        "Tell me more",
        config=cfg,
        options=Options(continue_from=previous),
    )

    assert len(fake.generate_kwargs) == 1
    received_history = fake.generate_kwargs[0]["request"].history
    assert len(received_history) == 3
    # Verify tool message was preserved (not filtered out)
    assert received_history[2].role == "tool"
    assert received_history[2].tool_call_id == "call_1"
    # Verify assistant tool_calls preserved
    assert received_history[1].tool_calls is not None


@pytest.mark.asyncio
async def test_continue_from_forwards_provider_state_with_history_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History item provider_state should be forwarded in request.provider_state."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="anthropic", model="claude-haiku-4-5", use_mock=True)

    previous: ResultEnvelope = {
        "status": "ok",
        "answers": [""],
        "_conversation_state": {
            "history": [
                {"role": "user", "content": "Question"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "name": "lookup", "arguments": "{}"}
                    ],
                    "provider_state": {
                        "anthropic_thinking_blocks": [
                            {
                                "type": "thinking",
                                "thinking": "plan",
                                "signature": "sig1",
                            }
                        ]
                    },
                },
            ]
        },
    }

    await pollux.run(
        None,
        config=cfg,
        options=Options(continue_from=previous),
    )

    req = fake.generate_kwargs[0]["request"]
    assert req.provider_state is not None
    history_state = req.provider_state.get("history")
    assert isinstance(history_state, list)
    assert history_state[0] is None
    assert history_state[1] == {
        "anthropic_thinking_blocks": [
            {"type": "thinking", "thinking": "plan", "signature": "sig1"}
        ]
    }


@pytest.mark.asyncio
async def test_continue_tool_mechanics(monkeypatch: pytest.MonkeyPatch) -> None:
    """continue_tool should neatly append tool results and allow None prompt."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    previous: ResultEnvelope = {
        "status": "ok",
        "answers": [""],
        "_conversation_state": {
            "history": [
                {"role": "user", "content": "What is the weather?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "name": "get_weather", "arguments": "{}"}
                    ],
                },
            ]
        },
    }

    tool_results = [
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 72}'}
    ]

    await pollux.continue_tool(
        continue_from=previous,
        tool_results=tool_results,
        config=cfg,
    )

    assert len(fake.generate_kwargs) == 1
    received_history = fake.generate_kwargs[0]["request"].history
    assert len(received_history) == 3
    assert received_history[2].role == "tool"
    assert received_history[2].content == '{"temp": 72}'

    # The prompt part of the internal run() call should be empty since prompt is None
    assert fake.generate_kwargs[0]["request"].parts == []
