"""Contract tests for conversation extension following contract-first pattern."""

from unittest.mock import MagicMock

import pytest

from pollux.extensions.conversation import (
    Conversation,
)
from pollux.extensions.conversation_modes import (
    SequentialMode,
    SingleMode,
    VectorizedMode,
)
from pollux.extensions.conversation_planner import (
    ConversationPlan,
    compile_conversation,
)
from pollux.extensions.conversation_types import (
    ConversationPolicy,
    ConversationState,
    PromptSet,
)

# Mark all tests in this module as contract tests
pytestmark = pytest.mark.contract


@pytest.fixture
def mock_executor():
    """Mock GeminiExecutor for testing."""
    executor = MagicMock()
    executor.config = MagicMock()
    executor.config.to_frozen.return_value = MagicMock()
    return executor


@pytest.fixture
def mock_result():
    """Mock execution result."""
    return {
        "status": "ok",
        "answers": ["This is a test response."],
        "metrics": {
            "token_validation": {
                "estimated_min": 10,
                "estimated_max": 50,
                "actual": 25,
                "in_range": True,
            }
        },
        "usage": {"total_tokens": 25},
    }


class TestConversationContracts:
    """Test core contracts and invariants of the conversation extension."""

    def test_conversation_state_immutability_contract(self):
        """Contract: ConversationState must be immutable after creation."""
        state = ConversationState(
            sources=("doc.pdf",),
            turns=(),
            policy=ConversationPolicy(),
        )

        # Should not be able to modify state
        with pytest.raises(AttributeError):
            state.sources = ("modified.pdf",)  # type: ignore

        with pytest.raises(AttributeError):
            state.version = 999  # type: ignore

    def test_conversation_policy_immutability_contract(self):
        """Contract: ConversationPolicy must be immutable after creation."""
        policy = ConversationPolicy(keep_last_n=5, widen_max_factor=1.2)

        # Should not be able to modify policy
        with pytest.raises(AttributeError):
            policy.keep_last_n = 10  # type: ignore

        with pytest.raises(AttributeError):
            policy.widen_max_factor = 1.5  # type: ignore

    def test_prompt_set_immutability_contract(self):
        """Contract: PromptSet must be immutable after creation."""
        ps = PromptSet(("Hello", "World"), SequentialMode())

        # Should not be able to modify prompt set
        with pytest.raises(AttributeError):
            ps.prompts = ("Modified",)  # type: ignore

        with pytest.raises(AttributeError):
            ps.mode = VectorizedMode()  # type: ignore

    def test_conversation_plan_immutability_contract(self):
        """Contract: ConversationPlan must be immutable after creation."""
        plan = ConversationPlan(
            sources=("doc.pdf",),
            history=(),
            prompts=("Hello",),
            strategy="sequential",
            hints=(),
        )

        # Should not be able to modify plan
        with pytest.raises(AttributeError):
            plan.prompts = ("Modified",)  # type: ignore

        with pytest.raises(AttributeError):
            plan.strategy = "vectorized"  # type: ignore

    def test_compile_conversation_pure_function_contract(self):
        """Contract: compile_conversation must be a pure function."""
        state1 = ConversationState(
            sources=("doc.pdf",),
            turns=(),
            policy=ConversationPolicy(keep_last_n=3),
        )
        state2 = ConversationState(
            sources=("doc.pdf",),
            turns=(),
            policy=ConversationPolicy(keep_last_n=3),
        )
        prompt_set = PromptSet(("Test prompt",), SingleMode())

        # Same inputs should produce same outputs
        plan1 = compile_conversation(state1, prompt_set, state1.policy)
        plan2 = compile_conversation(state2, prompt_set, state2.policy)

        assert plan1 == plan2
        assert plan1.sources == plan2.sources
        assert plan1.prompts == plan2.prompts
        assert plan1.strategy == plan2.strategy

    def test_conversation_operations_return_new_instances_contract(self):
        """Contract: Conversation operations must return new instances, not modify existing ones."""
        mock_executor = MagicMock()
        conv = Conversation.start(mock_executor, sources=["doc.pdf"])
        original_state = conv.state

        # with_policy should return new instance
        new_conv = conv.with_policy(ConversationPolicy(keep_last_n=5))
        assert new_conv is not conv
        assert new_conv.state is not original_state

        # with_sources should return new instance
        newer_conv = conv.with_sources("new.pdf")
        assert newer_conv is not conv
        assert newer_conv.state is not original_state

    def test_single_pipeline_seam_contract(self):
        """Contract: All execution must go through the single pipeline seam."""
        state = ConversationState(
            sources=("doc.pdf",),
            turns=(),
            policy=ConversationPolicy(),
        )
        prompt_set = PromptSet(("Test prompt",), SingleMode())

        # Compile plan (pure function)
        plan = compile_conversation(state, prompt_set, state.policy)

        # Verify plan structure
        assert isinstance(plan, ConversationPlan)
        assert plan.sources == ("doc.pdf",)
        assert plan.prompts == ("Test prompt",)

    def test_data_centric_design_contract(self):
        """Contract: Design must be data-centric with behavior driven by data."""
        # Create policy data that controls behavior
        policy = ConversationPolicy(
            keep_last_n=2,
            widen_max_factor=1.1,
            clamp_max_tokens=16000,
            prefer_json_array=True,
            execution_cache_name="test_cache",
        )

        # Create prompt set data that controls execution mode
        prompt_set = PromptSet(("Q1", "Q2", "Q3"), VectorizedMode())

        # Compile with data inputs
        state = ConversationState(sources=("doc.pdf",), turns=())
        plan = compile_conversation(state, prompt_set, policy)

        # Verify data-driven behavior
        # Vectorized mode maps to vectorized strategy in the planner
        assert plan.strategy == "vectorized"
        assert len(plan.hints) > 0  # From policy settings
        assert plan.prompts == ("Q1", "Q2", "Q3")  # From prompt_set

    def test_plan_inspectability_contract(self):
        """Contract: ConversationPlan must be inspectable for auditability."""
        policy = ConversationPolicy(keep_last_n=3, widen_max_factor=1.2)
        prompt_set = PromptSet(("Q1", "Q2"), SequentialMode())
        state = ConversationState(sources=("doc.pdf",), turns=())

        plan = compile_conversation(state, prompt_set, policy)

        # Plan must be inspectable via attributes
        assert hasattr(plan, "sources")
        assert hasattr(plan, "prompts")
        assert hasattr(plan, "strategy")
        assert hasattr(plan, "hints")

        # Verify the plan structure
        assert plan.sources == ("doc.pdf",)
        assert plan.prompts == ("Q1", "Q2")
        assert plan.strategy == "sequential"

    def test_policy_constructors_contract(self):
        """Contract: Policy constructors must create valid policies."""
        # Test default policy construction
        policy = ConversationPolicy()

        assert isinstance(policy, ConversationPolicy)

        # Verify default values
        assert policy.keep_last_n is None
        assert policy.widen_max_factor is None
        assert policy.clamp_max_tokens is None
        assert policy.prefer_json_array is False

    def test_prompt_set_constructors_contract(self):
        """Contract: PromptSet constructors must create valid prompt sets."""
        # Test direct construction of PromptSet
        single = PromptSet(("Hello",), SingleMode())
        seq = PromptSet(("Q1", "Q2", "Q3"), SequentialMode())
        vec = PromptSet(("A", "B", "C"), VectorizedMode())

        assert single.mode == SingleMode()
        assert single.prompts == ("Hello",)

        assert seq.mode == SequentialMode()
        assert seq.prompts == ("Q1", "Q2", "Q3")

        assert vec.mode == VectorizedMode()
        assert vec.prompts == ("A", "B", "C")
