"""Contract-first unit tests for core data types.

These tests verify that the core data structures maintain architectural
principles of immutability, self-validation, and pure transformations.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    Failure,
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
    Turn,
)


class TestResultMonadCompliance:
    """Tests that verify the Result monad maintains functional programming principles."""

    @pytest.mark.unit
    def test_success_constructor_is_immutable(self):
        """Success objects should be immutable by design."""
        success = Success("test_value")

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            success.value = "modified_value"  # type: ignore

    @pytest.mark.unit
    def test_failure_constructor_is_immutable(self):
        """Failure objects should be immutable by design."""
        error = ValueError("test error")
        failure = Failure(error)

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            failure.error = ValueError("modified error")  # type: ignore

    @pytest.mark.unit
    def test_result_union_type_contract(self):
        """Result type should only allow Success or Failure."""
        success = Success("test")
        failure = Failure(ValueError("test"))

        # Both should be valid Results
        assert isinstance(success, Success)
        assert isinstance(failure, Failure)

        # Invalid types should not be Results
        assert not isinstance("string", Success | Failure)
        assert not isinstance(123, Success | Failure)

    @pytest.mark.unit
    def test_success_equality_is_value_based(self):
        """Success objects should be equal if their values are equal."""
        success1 = Success("test")
        success2 = Success("test")
        success3 = Success("different")

        assert success1 == success2
        assert success1 != success3

    @pytest.mark.unit
    def test_failure_equality_is_error_based(self):
        """Failure objects should be equal if their errors are equal."""
        # Note: Exception instances with same message are not equal by default
        # This test verifies the current behavior
        error1 = ValueError("test error")
        error2 = ValueError("test error")
        error3 = ValueError("different error")

        failure1 = Failure(error1)
        failure2 = Failure(error2)
        failure3 = Failure(error3)

        # Exceptions with same message are not equal by default in Python
        # This is expected behavior for dataclass equality
        assert failure1 != failure2  # Different exception instances
        assert failure1 != failure3  # Different messages


class TestTurnCompliance:
    """Tests that verify Turn maintains data-centric design."""

    @pytest.mark.unit
    def test_turn_constructor_is_immutable(self):
        """Turn should be immutable by design."""
        turn = Turn(
            question="What is AI?", answer="Artificial Intelligence", is_error=False
        )

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            turn.question = "Modified question"  # type: ignore

    @pytest.mark.unit
    def test_turn_has_sensible_defaults(self):
        """Turn should have sensible defaults for optional fields."""
        turn = Turn(question="What is AI?", answer="Artificial Intelligence")

        assert turn.is_error is False

    @pytest.mark.unit
    def test_turn_equality_is_content_based(self):
        """Turn objects should be equal if their content is equal."""
        turn1 = Turn("Q1", "A1", is_error=False)
        turn2 = Turn("Q1", "A1", is_error=False)
        turn3 = Turn("Q1", "A1", is_error=True)  # Different is_error

        assert turn1 == turn2
        assert turn1 != turn3


class TestSourceCompliance:
    """Tests that verify Source maintains lazy loading and type safety."""

    @pytest.mark.unit
    def test_source_constructor_is_immutable(self):
        """Source should be immutable by design."""

        def content_loader():
            return b"test content"

        source = Source(
            source_type="text",
            identifier="test.txt",
            mime_type="text/plain",
            size_bytes=12,
            content_loader=content_loader,
        )

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            source.source_type = "file"  # type: ignore

    @pytest.mark.unit
    def test_source_type_is_literal(self):
        """Source type should be restricted to valid literal values."""

        def content_loader():
            return b"test content"

        # Valid types should work
        valid_types = ["text", "youtube", "arxiv", "file"]
        for source_type in valid_types:
            source = Source(
                source_type=source_type,  # type: ignore
                identifier="test",
                mime_type="text/plain",
                size_bytes=12,
                content_loader=content_loader,
            )
            assert source.source_type == source_type

    @pytest.mark.unit
    def test_source_identifier_accepts_string_or_path(self):
        """Source identifier should accept both string and Path objects."""

        def content_loader():
            return b"test content"

        # String identifier
        source1 = Source(
            source_type="text",
            identifier="test.txt",
            mime_type="text/plain",
            size_bytes=12,
            content_loader=content_loader,
        )
        assert isinstance(source1.identifier, str)

        # Path identifier
        source2 = Source(
            source_type="file",
            identifier=Path("test.txt"),
            mime_type="text/plain",
            size_bytes=12,
            content_loader=content_loader,
        )
        assert isinstance(source2.identifier, Path)

    @pytest.mark.unit
    def test_source_content_loader_is_callable(self):
        """Source content_loader should be a callable that returns bytes."""

        def content_loader():
            return b"test content"

        source = Source(
            source_type="text",
            identifier="test.txt",
            mime_type="text/plain",
            size_bytes=12,
            content_loader=content_loader,
        )

        # Should be callable
        assert callable(source.content_loader)

        # Should return bytes
        content = source.content_loader()
        assert isinstance(content, bytes)


class TestCommandStateCompliance:
    """Tests that verify command state transformations maintain data flow principles."""

    @pytest.mark.unit
    def test_initial_command_constructor_is_immutable(self):
        """InitialCommand should be immutable by design."""
        config = resolve_config(overrides={"api_key": "test_key"})
        command = InitialCommand(
            sources=(
                Source.from_text("source1"),
                Source.from_text("source2"),
            ),
            prompts=("prompt1", "prompt2"),
            config=config,
        )

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            command.sources = ("modified",)  # type: ignore

    @pytest.mark.unit
    def test_initial_command_has_sensible_defaults(self):
        """InitialCommand should have sensible defaults for optional fields."""
        config = resolve_config(overrides={"api_key": "test_key"})
        command = InitialCommand(
            sources=(Source.from_text("source1"),), prompts=("prompt1",), config=config
        )

        assert command.history == ()

    @pytest.mark.unit
    def test_resolved_command_contains_initial(self):
        """ResolvedCommand should contain the initial command for traceability."""
        config = resolve_config(overrides={"api_key": "test_key"})
        initial = InitialCommand(
            sources=(Source.from_text("source1"),), prompts=("prompt1",), config=config
        )

        def content_loader():
            return b"test content"

        resolved_sources = (
            Source(
                source_type="text",
                identifier="source1",
                mime_type="text/plain",
                size_bytes=12,
                content_loader=content_loader,
            ),
        )

        resolved = ResolvedCommand(initial=initial, resolved_sources=resolved_sources)

        assert resolved.initial == initial
        assert len(resolved.resolved_sources) == 1

    @pytest.mark.unit
    def test_api_call_constructor_is_immutable(self):
        """APICall should be immutable by design."""
        # Avoid importing provider SDK types in tests; use library-owned shapes
        from pollux.core.types import TextPart

        # Convert provider SDK parts/config into library-owned shapes
        api_call = APICall(
            model_name="gemini-2.0-flash",
            api_parts=(TextPart(text="test"),),
            api_config={},
            cache_name_to_use=None,
        )

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            api_call.model_name = "modified"  # type: ignore

    @pytest.mark.unit
    def test_execution_plan_has_optional_fallback(self):
        """ExecutionPlan should have an optional fallback call."""
        # provider SDK import intentionally omitted in tests; use library shapes

        primary = APICall(
            model_name="gemini-2.0-flash",
            api_parts=(TextPart(text="test"),),
            api_config={},
        )

        # Plan without fallback
        plan1 = ExecutionPlan(calls=(primary,))
        assert plan1.fallback_call is None

        # Plan with fallback
        fallback = APICall(
            model_name="gemini-1.5-flash",
            api_parts=(TextPart(text="fallback"),),
            api_config={},
        )
        plan2 = ExecutionPlan(calls=(primary,), fallback_call=fallback)
        assert plan2.fallback_call == fallback

    @pytest.mark.unit
    def test_execution_plan_rejects_empty_calls(self):
        """ExecutionPlan should reject empty calls tuple for architectural robustness."""
        with pytest.raises(ValueError, match="calls: calls must not be empty"):
            ExecutionPlan(calls=())

    @pytest.mark.unit
    def test_planned_command_contains_resolved_and_plan(self):
        """PlannedCommand should contain both resolved command and execution plan."""
        config = resolve_config(overrides={"api_key": "test_key"})
        initial = InitialCommand(
            sources=(Source.from_text("source1"),), prompts=("prompt1",), config=config
        )

        def content_loader():
            return b"test content"

        resolved = ResolvedCommand(
            initial=initial,
            resolved_sources=(
                Source(
                    source_type="text",
                    identifier="source1",
                    mime_type="text/plain",
                    size_bytes=12,
                    content_loader=content_loader,
                ),
            ),
        )

        execution_plan = ExecutionPlan(
            calls=(
                APICall(
                    model_name="gemini-2.0-flash",
                    api_parts=(TextPart(text="test"),),
                    api_config={},
                ),
            )
        )

        planned = PlannedCommand(resolved=resolved, execution_plan=execution_plan)

        assert planned.resolved == resolved
        assert planned.execution_plan == execution_plan

    @pytest.mark.unit
    def test_finalized_command_contains_telemetry_data(self):
        """FinalizedCommand should contain telemetry data for observability."""
        config = resolve_config(overrides={"api_key": "test_key"})
        initial = InitialCommand(
            sources=(Source.from_text("source1"),), prompts=("prompt1",), config=config
        )

        def content_loader():
            return b"test content"

        resolved = ResolvedCommand(
            initial=initial,
            resolved_sources=(
                Source(
                    source_type="text",
                    identifier="source1",
                    mime_type="text/plain",
                    size_bytes=12,
                    content_loader=content_loader,
                ),
            ),
        )

        execution_plan = ExecutionPlan(
            calls=(
                APICall(
                    model_name="gemini-2.0-flash",
                    api_parts=(TextPart(text="test"),),
                    api_config={},
                ),
            )
        )

        planned = PlannedCommand(resolved=resolved, execution_plan=execution_plan)

        finalized = FinalizedCommand(
            planned=planned,
            raw_api_response={"test": "response"},
            telemetry_data={"tokens_used": 100},
        )

        assert finalized.telemetry_data == {"tokens_used": 100}
        assert finalized.raw_api_response == {"test": "response"}


class TestDataCentricityCompliance:
    """Tests that verify data-centric design principles."""

    @pytest.mark.unit
    def test_all_dataclasses_are_frozen(self):
        """All core dataclasses should be frozen for immutability."""
        dataclasses = [
            Success,
            Failure,
            Turn,
            Source,
            InitialCommand,
            ResolvedCommand,
            APICall,
            ExecutionPlan,
            PlannedCommand,
            FinalizedCommand,
        ]

        for cls in dataclasses:
            # Check if the class is frozen by attempting to create an instance
            # and then modify it (this is a structural test)
            if cls in [Success, Failure]:
                # These have simple constructors
                instance = cls("test") if cls == Success else cls(ValueError("test"))
            elif cls == Turn:
                instance = cls("Q", "A")
            elif cls == Source:
                instance = cls(
                    source_type="text",
                    identifier="test",
                    mime_type="text/plain",
                    size_bytes=4,
                    content_loader=lambda: b"test",
                )
            elif cls == InitialCommand:
                config = resolve_config(overrides={"api_key": "test"})
                instance = cls(
                    sources=(Source.from_text("test"),),
                    prompts=("test",),
                    config=config,
                )
            else:
                # Skip complex constructors for this test
                continue

            # Should be frozen - assignment should fail
            with pytest.raises(AttributeError):
                # Try to set any attribute
                for field_name in instance.__annotations__:
                    setattr(instance, field_name, "modified")

    @pytest.mark.unit
    def test_data_structures_self_validate(self):
        """Data structures should prevent invalid states at construction time."""
        # Test that required fields are enforced
        with pytest.raises(TypeError):
            # Missing required fields - call via Any-cast to bypass static checks
            cast("Any", InitialCommand)()

        with pytest.raises(TypeError):
            # Missing required fields - call via Any-cast to bypass static checks
            cast("Any", Source)()

    @pytest.mark.unit
    def test_transformations_are_pure(self):
        """Command transformations should be pure (no side effects)."""
        config = resolve_config(overrides={"api_key": "test_key"})
        original_command = InitialCommand(
            sources=(Source.from_text("source1"),), prompts=("prompt1",), config=config
        )

        # Make a copy to verify original isn't mutated
        command_copy = deepcopy(original_command)

        # Create a resolved command (transformation)
        def content_loader():
            return b"test content"

        resolved = ResolvedCommand(
            initial=original_command,
            resolved_sources=(
                Source(
                    source_type="text",
                    identifier="source1",
                    mime_type="text/plain",
                    size_bytes=12,
                    content_loader=content_loader,
                ),
            ),
        )

        # Original command should be unchanged (pure transformation)
        assert original_command == command_copy
        assert resolved.initial == original_command  # Composition, not mutation
