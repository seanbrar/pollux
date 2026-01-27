from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from pollux.extensions import Conversation, PromptSet
from pollux.extensions.conversation_planner import compile_conversation
from pollux.extensions.conversation_types import ConversationPolicy

if TYPE_CHECKING:
    from pollux.core.commands import InitialCommand
    from pollux.core.result_envelope import ResultEnvelope


class _StubConfig:
    def to_frozen(self) -> Any:
        return self


class _StubExecutor:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.config: Any = _StubConfig()

    async def execute(self, _command: InitialCommand) -> ResultEnvelope:
        # Echo prompts into answers if not provided in result
        prompts = _command.prompts
        result: ResultEnvelope = self._result.copy()  # type: ignore
        if "answers" not in result:
            result["answers"] = [f"echo:{p}" for p in prompts]
        return result


def _base_envelope() -> dict[str, Any]:
    return {
        "status": "ok",
        "answers": [],
        "extraction_method": "stub",
        "confidence": 1.0,
        "usage": {},
        "metrics": {"token_validation": {}},
    }


@pytest.mark.asyncio
async def test_run_distributes_metrics_and_adds_warnings() -> None:
    # Force missing per_prompt; provide usage and token_validation that triggers warning
    env = _base_envelope()
    env["answers"] = ["A1", "A2", "A3"]
    env["usage"] = {"total_tokens": 120, "prompt_tokens": 30, "completion_tokens": 90}
    env["metrics"] = {
        "token_validation": {"estimated_max": 100, "actual": 250, "in_range": False}
    }
    env["validation_warnings"] = ["schema drift"]

    conv = Conversation.start(_StubExecutor(env))
    conv2, answers, metrics = await conv.run(PromptSet.sequential("Q1", "Q2", "Q3"))

    # Three new turns with warnings only on the first
    assert len(conv2.state.turns) == 3
    assert answers == ("A1", "A2", "A3")
    assert "schema drift" in conv2.state.turns[0].warnings
    assert any("exceeded estimate" in w for w in conv2.state.turns[0].warnings)
    assert conv2.state.turns[1].warnings == ()
    assert conv2.state.turns[2].warnings == ()

    # Per-prompt metrics distributed, totals taken from usage
    assert len(metrics.per_prompt) == 3
    assert metrics.totals.get("total_tokens") == 120


@pytest.mark.asyncio
async def test_run_uses_per_prompt_metrics_when_provided() -> None:
    env = _base_envelope()
    env["answers"] = ["A1", "A2"]
    env["usage"] = {"total_tokens": 50}
    env["metrics"] = {
        "per_prompt": [{"tok": 10}, {"tok": 40}],
        "token_validation": {"estimated_max": 60, "actual": 50, "in_range": True},
    }

    conv = Conversation.start(_StubExecutor(env))
    _, answers, metrics = await conv.run(PromptSet.sequential("Q1", "Q2"))

    assert answers == ("A1", "A2")
    assert metrics.per_prompt == ({"tok": 10}, {"tok": 40})


@pytest.mark.asyncio
async def test_run_totals_fallback_from_metrics_when_usage_missing() -> None:
    env = _base_envelope()
    env["answers"] = ["A1"]
    # No usage object; totals should come from numeric metrics keys
    env.pop("usage", None)
    env["metrics"] = {
        "foo": 7,
        "bar": 3.0,
        "token_validation": {"estimated_max": 5, "actual": 7, "in_range": False},
    }

    conv = Conversation.start(_StubExecutor(env))
    _, _, metrics = await conv.run(PromptSet.single("Q1"))
    assert metrics.totals.get("foo") == 7
    assert metrics.totals.get("bar") == 3.0


def test_with_sources_string_handling() -> None:
    conv = Conversation.start(_StubExecutor(_base_envelope()))
    conv2 = conv.with_sources("/path/to/file.txt")
    assert conv2.state.sources == ("/path/to/file.txt",)


def test_policy_affects_options_and_hints() -> None:
    policy = ConversationPolicy(
        keep_last_n=2,
        widen_max_factor=1.5,
        clamp_max_tokens=1000,
        prefer_json_array=True,
        execution_cache_name="cache-demo",
        reuse_cache_only=True,
    )
    conv = Conversation.start(_StubExecutor(_base_envelope()), sources=("doc.pdf",))
    plan = compile_conversation(conv.state, PromptSet.single("Q"), policy)
    # options present with fields set; hints view non-empty
    assert plan.options is not None
    assert plan.options.result is not None and plan.options.result.prefer_json_array
    assert plan.options.cache_override_name == "cache-demo"
    assert isinstance(plan.hints, tuple) and len(plan.hints) > 0


@pytest.mark.asyncio
async def test_vectorized_combines_prompts_and_answers() -> None:
    env = _base_envelope()
    env["answers"] = ["A1", "A2"]
    conv = Conversation.start(_StubExecutor(env))
    conv2, answers, _ = await conv.run(PromptSet.vectorized("Q1", "Q2"))
    assert len(conv2.state.turns) == 1
    assert answers == ("A1", "A2")
    assert conv2.state.turns[0].user.startswith("[vectorized x2]")
    assert (
        "A1" in conv2.state.turns[0].assistant
        and "A2" in conv2.state.turns[0].assistant
    )


@pytest.mark.asyncio
async def test_sequential_extra_answers_warn_only_first() -> None:
    env = _base_envelope()
    env["answers"] = ["A1", "A2"]
    conv = Conversation.start(_StubExecutor(env))
    conv2, _, _ = await conv.run(PromptSet.sequential("Q1"))
    assert len(conv2.state.turns) == 1
    assert len(conv2.state.turns[0].warnings) >= 1
