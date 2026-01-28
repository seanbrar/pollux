"""Comprehensive test suite for the Conversation extension.

Consolidates fragmented unit tests for the facade, planner, engine, and persistence
layers, maintaining architectural signal while improving suite maintainability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from pollux.core.exceptions import InvariantViolationError
from pollux.extensions import Conversation, PromptSet
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_modes import (
    VectorizedMode,
)
from pollux.extensions.conversation_planner import (
    compile_conversation,
)
from pollux.extensions.conversation_store import JSONStore
from pollux.extensions.conversation_types import (
    ConversationPolicy,
    ConversationState,
    Exchange,
)

from ._builders import make_exchange, make_state

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.core.commands import InitialCommand
    from pollux.core.result_envelope import ResultEnvelope

pytestmark = pytest.mark.unit


# --- Stubs & Helpers ---


class _StubConfig:
    def to_frozen(self) -> Any:
        return self


class _StubExecutor:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.config: Any = _StubConfig()

    async def execute(self, _command: InitialCommand) -> ResultEnvelope:
        prompts = _command.prompts
        result = self._result.copy()
        result.setdefault("answers", [f"echo:{p}" for p in prompts])
        return cast("ResultEnvelope", result)


def _base_envelope() -> dict[str, Any]:
    return {
        "status": "ok",
        "answers": [],
        "extraction_method": "stub",
        "confidence": 1.0,
        "usage": {},
        "metrics": {"token_validation": {}},
    }


# --- Test Cases ---


class TestConversationFacade:
    """Tests for the Conversation facade methods (start, with_*, analytics)."""

    @pytest.mark.asyncio
    async def test_basic_facade_flow(self, executor):
        """Test starting a conversation and basic mutations."""
        conv = Conversation.start(executor, sources=())
        assert len(conv.state.turns) == 0
        assert conv.state.sources == ()

        # Immutability check
        policy = ConversationPolicy(keep_last_n=5)
        conv_p = conv.with_policy(policy)
        assert conv_p is not conv
        assert conv_p.state.policy is not None
        assert conv_p.state.policy.keep_last_n == 5

        conv_s = conv.with_sources(["doc.pdf"])
        assert conv_s.state.sources == ("doc.pdf",)
        assert conv.state.sources == ()  # Original unchanged

    @pytest.mark.asyncio
    async def test_ask_and_run_methods(self, executor):
        """Test the high-level ask and run interfaces."""
        conv = Conversation.start(executor)
        # ask should increment turns
        conv2 = await conv.ask("Question?")
        assert len(conv2.state.turns) == 1

        # run should return tuple
        conv3, answers, metrics = await conv2.run(PromptSet.single("Another?"))
        assert len(conv3.state.turns) == 2
        assert len(answers) == 1
        assert hasattr(metrics, "totals")

    def test_analytics_computations(self, executor):
        """Test analytics for empty and populated conversations."""
        conv = Conversation.start(executor)
        a0 = conv.analytics()
        assert a0.total_turns == 0
        assert a0.success_rate == 1.0

        turns = [
            make_exchange("Q1", "A1", error=False, estimate_max=100, actual_tokens=80),
            make_exchange("Q2", "A2", error=True, estimate_max=50, actual_tokens=None),
        ]
        conv2 = Conversation(
            ConversationState(sources=(), turns=tuple(turns)), executor
        )
        a2 = conv2.analytics()
        assert a2.total_turns == 2
        assert a2.error_turns == 1
        assert a2.success_rate == 0.5
        assert a2.total_estimated_tokens == 150
        assert a2.total_actual_tokens == 80


class TestConversationPlanner:
    """Tests for the Conversation Planner and compilation logic."""

    def test_compile_conversation_basic_and_window(self):
        """Test basic compilation and history window application."""
        turns = (
            Exchange("q1", "a1", error=False),
            Exchange("q2", "a2", error=False),
            Exchange("q3", "a3", error=False),
        )
        state = make_state(sources=("doc.pdf",), turns=turns)
        policy = ConversationPolicy(keep_last_n=2)
        ps = PromptSet.single("New")

        plan = compile_conversation(state, ps, policy)
        assert plan.strategy == "sequential"
        assert len(plan.history) == 2
        assert plan.history[0].question == "q2"

    def test_compile_cache_and_policy_hints(self):
        """Test that cache and policy settings properly influence execution hints."""
        state = make_state(sources=("d.pdf",), cache_key="k1")
        policy = ConversationPolicy(widen_max_factor=1.2, reuse_cache_only=True)
        plan = compile_conversation(state, PromptSet.single("Q"), policy)

        assert plan.options is not None
        assert plan.options.cache is not None
        assert plan.options.estimation is not None
        assert plan.options.cache.deterministic_key == "k1"
        assert plan.options.cache.reuse_only is True
        assert plan.options.estimation.widen_max_factor == 1.2

        hint_names = [type(h).__name__ for h in plan.hints]
        assert "CacheOptions" in hint_names
        assert "EstimationOptions" in hint_names

    def test_prompt_set_modes(self):
        """Test PromptSet constructors and mode behavior."""
        ps_vec = PromptSet.vectorized("Q1", "Q2")
        assert ps_vec.mode == VectorizedMode()

        plan = compile_conversation(make_state(), ps_vec, ConversationPolicy())
        assert plan.strategy == "vectorized"
        assert plan.prompts == ("Q1", "Q2")


class TestConversationEngine:
    """Tests for the internal ConversationEngine and persistence."""

    @pytest.mark.asyncio
    async def test_engine_appends_with_version_and_handles_bad_envelope(
        self, mock_executor
    ):
        store = MagicMock()
        init_state = make_state(version=3)
        store.load = AsyncMock(return_value=init_state)
        store.append = AsyncMock()

        mock_executor.execute = AsyncMock(
            return_value={**_base_envelope(), "answers": ["ok"]}
        )
        engine = ConversationEngine(mock_executor, store)

        # Success path
        await engine.ask("c1", "Hi")
        assert store.append.await_args.kwargs.get("expected_version") == 3

        # Failure path: invalid envelope
        mock_executor.execute = AsyncMock(return_value={"unexpected": True})
        with pytest.raises(InvariantViolationError):
            await engine.ask("c2", "boom")

    @pytest.mark.asyncio
    async def test_json_store_round_trip(self, tmp_path: Path) -> None:
        store = JSONStore(str(tmp_path / "store.json"))
        ex = Exchange(user="u", assistant="a", error=False, warnings=("w1",))
        await store.append("rt", expected_version=0, ex=ex)

        state = await store.load("rt")
        assert state.version == 1
        assert state.turns[-1].warnings == ("w1",)

    @pytest.mark.asyncio
    async def test_json_store_occ_conflict(self, tmp_path: Path) -> None:
        """Verify optimistic concurrency control conflict."""
        store = JSONStore(str(tmp_path / "store.json"))
        # Initial turn
        await store.append(
            "occ", expected_version=0, ex=Exchange("u", "a", error=False)
        )

        # Current version is 1. Attempting append expecting 0 should fail.
        with pytest.raises(RuntimeError):
            await store.append(
                "occ", expected_version=0, ex=Exchange("u2", "a2", error=False)
            )


class TestAdvancedBehaviors:
    """Tests for metrics distribution, modes, and edge cases."""

    @pytest.mark.asyncio
    async def test_metrics_distribution_and_warnings(self):
        env = _base_envelope()
        env.update(
            {
                "answers": ["A1", "A2"],
                "usage": {"total_tokens": 100},
                "validation_warnings": ["drift"],
            }
        )
        executor = _StubExecutor(env)
        conv = Conversation.start(executor)

        conv2, _answers, metrics = await conv.run(PromptSet.sequential("Q1", "Q2"))
        assert len(conv2.state.turns) == 2
        assert "drift" in conv2.state.turns[0].warnings
        assert metrics.totals.get("total_tokens") == 100

    @pytest.mark.asyncio
    async def test_vectorized_mode_formatting(self):
        env = _base_envelope()
        env["answers"] = ["A1", "A2"]
        executor = _StubExecutor(env)
        conv = Conversation.start(executor)

        conv2, _, _ = await conv.run(PromptSet.vectorized("Q1", "Q2"))
        assert len(conv2.state.turns) == 1
        assert conv2.state.turns[0].user.startswith("[vectorized x2]")
        assert "A1" in conv2.state.turns[0].assistant
        assert "A2" in conv2.state.turns[0].assistant

    def test_state_immutability(self):
        state = make_state(sources=("doc.pdf",), turns=())
        with pytest.raises(AttributeError):
            state.sources = ("mod.pdf",)  # type: ignore
