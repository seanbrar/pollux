import inspect
from typing import TYPE_CHECKING, Any

import pytest

from pollux.core import exceptions, models, types

if TYPE_CHECKING:
    from collections.abc import Callable


class TestSimplicityCompliance:
    """Tests that verify the core module maintains architectural simplicity."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_core_module_has_minimal_public_interface(self):
        """The core module should have a minimal, focused public interface."""
        # Assert an intentional, curated public surface for discoverability.
        # This is more robust than a raw count and documents the contract.
        actual = {
            name
            for name in dir(types)
            if not name.startswith("_") and not inspect.ismodule(getattr(types, name))
        }
        expected = {
            "APICall",
            "APIPart",
            "Turn",
            "ExecutionPlan",
            "Failure",
            "FileInlinePart",
            "FilePlaceholder",
            "FileRefPart",
            "FinalizedCommand",
            "GenerationConfigDict",
            "HistoryPart",
            "InitialCommand",
            "PlannedCommand",
            "PromptBundle",
            "RateConstraint",
            "ResolvedCommand",
            "Result",
            "ResultEnvelope",
            "Source",
            "Success",
            "TextPart",
            "TokenEstimate",
            "UploadTask",
            "explain_invalid_result_envelope",
            "is_result_envelope",
        }
        assert actual == expected, (
            f"Public surface mismatch. Extra: {sorted(actual - expected)}; "
            f"Missing: {sorted(expected - actual)}"
        )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_dataclasses_have_simple_constructors(self):
        """Dataclasses should have simple, obvious constructors."""
        dataclasses = [
            types.Success,
            types.Failure,
            types.Turn,
            types.Source,
            types.InitialCommand,
            types.ResolvedCommand,
            models.RateLimits,
            models.CachingCapabilities,
            models.ModelCapabilities,
        ]
        for cls in dataclasses:
            sig = inspect.signature(cls)

            # Should have reasonable number of parameters (not too complex)
            param_count = len(sig.parameters)
            assert param_count <= 6, (
                f"{cls.__name__} has too many parameters: {param_count}"
            )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_functions_have_simple_signatures(self):
        """Functions should have simple, clear signatures."""
        functions: list[Callable[..., Any]] = [
            models.get_model_capabilities,
            models.get_rate_limits,
            models.can_use_caching,
        ]
        for func in functions:
            sig = inspect.signature(func)

            # Should have reasonable number of parameters
            param_count = len(sig.parameters)
            assert param_count <= 3, (
                f"{func.__name__} has too many parameters: {param_count}"
            )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_no_complex_inheritance_hierarchies(self):
        """The core module should avoid complex inheritance hierarchies."""
        # Check that exceptions have simple inheritance
        exception_classes = [
            exceptions.PolluxError,
            exceptions.APIError,
            exceptions.PipelineError,
            exceptions.ConfigurationError,
            exceptions.SourceError,
            exceptions.MissingKeyError,
            exceptions.FileError,
            exceptions.ValidationError,
            exceptions.UnsupportedContentError,
        ]

        for cls in exception_classes:
            # Should have simple inheritance (max 4 levels including object)
            # This accounts for: Class -> PolluxError -> Exception -> BaseException -> object
            mro = cls.__mro__
            assert len(mro) <= 5, f"{cls.__name__} has complex inheritance: {mro}"
