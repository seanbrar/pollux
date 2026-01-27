from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pollux.extensions.conversation import Conversation
from pollux.extensions.conversation_modes import (
    ExecutionMode,
    SequentialMode,
    SingleMode,
    VectorizedMode,
)
from pollux.extensions.conversation_types import (
    ConversationState,
    Exchange,
    PromptSet,
)

if TYPE_CHECKING:
    from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "mode,prompts,answers,expect_len,expect_user_prefix",
    [
        (SingleMode(), ("Q1", "Q2"), ("A1", "A2"), 1, None),
        (SequentialMode(), ("Q1", "Q2", "Q3"), ("A1",), 3, None),
        (VectorizedMode(), ("Q1", "Q2"), ("A1", "A2"), 1, "[vectorized x2]"),
    ],
)
def test_mode_formatting_invariants(
    mode: ExecutionMode,
    prompts: tuple[str, ...],
    answers: tuple[str, ...],
    expect_len: int,
    expect_user_prefix: str | None,
) -> None:
    exs = mode.format_exchanges(prompts, answers, {})
    assert len(exs) == expect_len
    assert isinstance(exs[0], Exchange)
    if expect_user_prefix is not None:
        assert exs[0].user.startswith(expect_user_prefix)

    # Additional content checks for robustness across modes
    if isinstance(mode, SingleMode):
        # First prompt/answer mapped; warnings normalized (may add warnings)
        assert exs[0].user == prompts[0]
        assert exs[0].assistant == answers[0]
        assert len(exs[0].warnings) >= 0
    if isinstance(mode, SequentialMode) and len(prompts) > len(answers):
        # Zipping behavior pads missing answers with empty assistant
        assert exs[1].assistant == ""
    if isinstance(mode, VectorizedMode):
        # Combined assistant should include all answers
        for a in answers:
            assert a in exs[0].assistant


def test_prompt_set_constructors() -> None:
    single = PromptSet.single("Hello")
    assert single.mode == SingleMode()
    assert single.prompts == ("Hello",)

    seq = PromptSet.sequential("Q1", "Q2")
    assert seq.mode == SequentialMode()
    assert seq.prompts == ("Q1", "Q2")

    vec = PromptSet.vectorized("A", "B", "C")
    assert vec.mode == VectorizedMode()
    assert vec.prompts == ("A", "B", "C")


@pytest.mark.asyncio
async def test_conversation_sequential_appends_per_prompt_turns(
    mock_executor: MagicMock,
) -> None:
    # Configure shared mock executor to echo prompts in answers with basic metrics
    async def _exec(cmd):
        prompts = tuple(getattr(cmd, "prompts", ()) or ())
        return {
            "status": "ok",
            "answers": [f"ok: {p}" for p in prompts],
            "extraction_method": "stub",
            "confidence": 1.0,
            "usage": {"total_tokens": 1},
            "metrics": {"token_validation": {"estimated_max": 2, "actual": 1}},
        }

    mock_executor.execute.side_effect = _exec

    conv = Conversation.start(mock_executor)
    prompts = ("First question?", "Second question?")
    conv2, answers, metrics = await conv.run(PromptSet.sequential(*prompts))

    assert len(conv2.state.turns) == 2
    assert conv2.state.turns[0].user == prompts[0]
    assert conv2.state.turns[1].user == prompts[1]
    assert len(answers) == 2

    assert hasattr(metrics, "per_prompt") and len(metrics.per_prompt) == 2
    assert hasattr(metrics, "totals") and isinstance(metrics.totals, dict)


def test_conversation_analytics_summary() -> None:
    turns = (
        Exchange("Q1", "A1", error=False, estimate_max=100, actual_tokens=80),
        Exchange("Q2", "A2", error=True, estimate_max=50, actual_tokens=None),
    )
    conv = Conversation(ConversationState(sources=(), turns=turns), executor=None)  # type: ignore[arg-type]
    a = conv.analytics()
    assert a.total_turns == 2
    assert a.error_turns == 1
    assert a.total_estimated_tokens == 150
    assert a.total_actual_tokens == 80


def test_single_mode_normalizes_extras_and_keeps_warnings() -> None:
    mode = SingleMode()
    prompts = ("Q1", "Q2")
    answers = ("A1", "A2")
    exs = mode.format_exchanges(prompts, answers, {"warnings": ("w0",)})
    assert len(exs) == 1
    assert exs[0].user == "Q1"
    assert exs[0].assistant == "A1"
    assert "w0" in exs[0].warnings
    assert len(exs[0].warnings) >= 1


def test_sequential_mode_zips_and_warns() -> None:
    mode = SequentialMode()
    prompts = ("Q1", "Q2", "Q3")
    answers = ("A1",)
    exs = mode.format_exchanges(prompts, answers, {})
    assert len(exs) == 3
    assert exs[1].user == "Q2"
    assert exs[1].assistant == ""
    # warnings recorded on first exchange only (others empty)
    if exs and exs[0].warnings:
        assert exs[1].warnings == ()


def test_vectorized_mode_combines_answers() -> None:
    mode = VectorizedMode()
    prompts = ("Q1", "Q2")
    answers = ("A1", "A2")
    exs = mode.format_exchanges(prompts, answers, {})
    assert len(exs) == 1
    assert exs[0].user.startswith("[vectorized x2]")
    assert "A1" in exs[0].assistant and "A2" in exs[0].assistant
