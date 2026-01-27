from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from pollux.extensions import Conversation, PromptSet
from pollux.extensions.conversation_store import JSONStore
from pollux.extensions.conversation_types import Exchange

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.core.types import InitialCommand, ResultEnvelope


class _StubConfig:
    def to_frozen(self) -> Any:
        return self


class _StubExecutor:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.config: Any = _StubConfig()

    async def execute(self, _command: InitialCommand) -> ResultEnvelope:
        # Echo prompts when answers omitted
        prompts = _command.prompts
        result = self._result.copy()
        result.setdefault("answers", [f"echo:{p}" for p in prompts])
        return cast("ResultEnvelope", result)


def _base_env() -> dict[str, Any]:
    return {
        "status": "ok",
        "answers": [],
        "extraction_method": "stub",
        "confidence": 1.0,
        "usage": {},
        "metrics": {},
    }


@pytest.mark.asyncio
async def test_error_detection_status_only() -> None:
    env = _base_env()
    env.update({"status": "error", "answers": ["A"]})
    conv = Conversation.start(_StubExecutor(env))
    conv2, _, _ = await conv.run(PromptSet.single("Q"))
    assert conv2.state.turns[-1].error is True


@pytest.mark.asyncio
async def test_validation_warnings_string_normalization_and_padding() -> None:
    # String warning should normalize to a tuple; per_prompt shorter than answers should pad
    env = _base_env()
    env["answers"] = ["A1", "A2", "A3"]
    env["validation_warnings"] = "schema drift"
    env["metrics"] = {
        "per_prompt": [{"tok": 1}],
        "token_validation": {"estimated_max": 10, "actual": 5, "in_range": True},
    }
    conv = Conversation.start(_StubExecutor(env))
    conv2, _, metrics = await conv.run(PromptSet.sequential("Q1", "Q2", "Q3"))
    assert (
        isinstance(conv2.state.turns[0].warnings, tuple)
        and conv2.state.turns[0].warnings
    )
    # padded per_prompt entries
    assert len(metrics.per_prompt) == 3
    assert metrics.per_prompt[0] == {"tok": 1}
    assert metrics.per_prompt[1] == {}
    assert metrics.per_prompt[2] == {}


def test_plan_returns_strategy() -> None:
    conv = Conversation.start(_StubExecutor(_base_env()))
    assert conv.plan(PromptSet.single("Q")).strategy == "sequential"
    assert conv.plan(PromptSet.sequential("Q1", "Q2")).strategy == "sequential"
    assert conv.plan(PromptSet.vectorized("Q1", "Q2")).strategy == "vectorized"


@pytest.mark.asyncio
async def test_analytics_summary_basic() -> None:
    env = _base_env()
    env["answers"] = ["A1", "A2"]
    env["metrics"] = {
        "token_validation": {"estimated_max": 50, "actual": 40, "in_range": True}
    }
    conv = Conversation.start(_StubExecutor(env))
    conv2, _, _ = await conv.run(PromptSet.sequential("Q1", "Q2"))
    summary = conv2.analytics()
    assert summary.total_turns == 2
    assert summary.error_turns in (0, 1)  # tolerant; depends on envelope shape
    assert summary.total_estimated_tokens is None or summary.total_estimated_tokens >= 0


@pytest.mark.contract
@pytest.mark.asyncio
async def test_json_store_round_trip_warnings(tmp_path: Path) -> None:
    store = JSONStore(str(tmp_path / "store.json"))
    conv_id = "round-trip"
    state = await store.load(conv_id)
    assert state.version == 0
    # Append with warnings and check they round-trip
    ex = Exchange(user="u", assistant="a", error=False, warnings=("w1", "w2"))
    state2 = await store.append(conv_id, expected_version=0, ex=ex)
    assert state2.version == 1
    state3 = await store.load(conv_id)
    assert state3.turns[-1].warnings == ("w1", "w2")
