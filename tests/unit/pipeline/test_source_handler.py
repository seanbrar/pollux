"""Contract-First Tests for the SourceHandler.

These tests do NOT verify specific business logic (e.g., "does it correctly
parse a PDF?"). Instead, they verify that the SourceHandler component complies
with the architectural principles laid out in the `contract_first_testing.md`
document. They act as guardians of the architecture.
"""

from copy import deepcopy
import inspect
from typing import cast

import pytest

from pollux.config import resolve_config
from pollux.core.exceptions import SourceError
from pollux.core.sources import Source
from pollux.core.types import (
    Failure,
    InitialCommand,
    ResolvedCommand,
    Success,
)
from pollux.pipeline.source_handler import SourceHandler


class TestSourceHandlerContracts:
    """A test suite for verifying the architectural contracts of SourceHandler."""

    def test_contract_simplicity_and_elegance(self):
        """
        Verifies [Simplicity & Elegance].
        A simple component should require no complex setup. Its contract
        should be obvious from its signature.
        """
        # 1. Trivial setup: The handler should be stateless.
        try:
            handler = SourceHandler()
            assert handler is not None
        except Exception:
            pytest.fail("SourceHandler should not require complex initialization.")

        # 2. Obvious contract: The `handle` method signature must be explicit.
        sig = inspect.signature(handler.handle)
        assert "command" in sig.parameters
        # Accept forward-ref string annotations equally to avoid brittle failures
        param_ann = sig.parameters["command"].annotation
        assert param_ann == InitialCommand or str(param_ann) == "InitialCommand"
        # The return type is Union[Success[ResolvedCommand], Failure[Failure]]
        return_type_str = str(sig.return_annotation)
        assert "Success" in return_type_str and "ResolvedCommand" in return_type_str
        assert "Failure" in return_type_str

    @pytest.mark.asyncio
    async def test_contract_data_centricity(self):
        """
        Verifies [Data-Centricity].
        The handler must perform a pure transformation, taking one immutable
        data object and returning a new one without side effects.
        """
        handler = SourceHandler()
        original_command = InitialCommand(
            sources=(Source.from_text("test input"),),
            prompts=("test prompt",),
            config=resolve_config(overrides={"api_key": "test-key"}),
        )
        # Make a deep copy to ensure the original is not mutated.
        command_copy = deepcopy(original_command)

        # Act
        result = await handler.handle(original_command)

        # Assert: The original command object must be unchanged.
        assert original_command == command_copy, "Handler must not mutate its input."

        # Assert: The result must be a new, transformed data object.
        assert isinstance(result, Success)
        assert isinstance(result.value, ResolvedCommand)
        assert result.value.initial == original_command, (
            "Output should compose the input."
        )

    @pytest.mark.asyncio
    async def test_contract_clarity_and_explicitness(self):
        """
        Verifies [Clarity & Explicitness].
        The handler's output must depend only on its input, with no hidden
        state or "magic".
        """
        handler = SourceHandler()
        command = InitialCommand(
            sources=(Source.from_text("deterministic test"),),
            prompts=("deterministic question",),
            config=resolve_config(overrides={"api_key": "test-key"}),
        )

        # Act: Run the same command multiple times.
        result1 = await handler.handle(command)
        result2 = await handler.handle(command)

        # Assert: The results must be functionally identical.
        # Note: We can't use direct equality because content_loader functions
        # are different objects, but we can verify the structure and behavior.
        assert isinstance(result1, Success)
        assert isinstance(result2, Success)
        assert result1.value.initial == result2.value.initial
        assert len(result1.value.resolved_sources) == len(
            result2.value.resolved_sources
        )

        # Compare the actual content by calling the loaders
        for source1, source2 in zip(
            result1.value.resolved_sources, result2.value.resolved_sources, strict=False
        ):
            assert source1.source_type == source2.source_type
            assert source1.identifier == source2.identifier
            assert source1.mime_type == source2.mime_type
            assert source1.size_bytes == source2.size_bytes
            # Compare the actual content loaded by the functions
            assert source1.content_loader() == source2.content_loader()

    @pytest.mark.asyncio
    async def test_contract_architectural_robustness(self):
        """
        Verifies [Architectural Robustness].
        Errors must be handled explicitly through the Result type, not by
        throwing exceptions. The pipeline should not crash.
        """
        handler = SourceHandler()
        # Create a command with invalid source objects that the handler must reject
        # The handler expects Source objects, but we'll pass a raw string to trigger an error
        problematic_command = InitialCommand(
            sources=cast(
                "tuple[Source, ...]",
                (
                    # intentionally wrong to trigger validation
                    "not a source object",
                ),
            ),
            prompts=("test",),
            config=resolve_config(overrides={"api_key": "test-key"}),
        )

        # Act
        result = await handler.handle(problematic_command)

        # Assert: The handler MUST return a Failure with SourceError.
        assert isinstance(result, Failure)
        assert isinstance(result.error, SourceError)
        assert "explicit `Source` objects" in str(result.error)
