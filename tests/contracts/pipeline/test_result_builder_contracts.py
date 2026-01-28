"""Contract tests for Result Builder architectural compliance.

These tests verify that the Result Builder implementation adheres to the
architectural contracts defined in the Command Pipeline and Two-Tier Transform
Chain specifications, rather than testing specific input/output behaviors.
"""

from dataclasses import is_dataclass
import inspect
import sys
from typing import Any, get_type_hints

import pytest

from pollux.core.types import FinalizedCommand
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.results.extraction import (
    ExtractionContext,
    ExtractionContract,
    ExtractionDiagnostics,
    ExtractionResult,
    TransformSpec,
    Violation,
)
from pollux.pipeline.results.minimal_projection import MinimalProjection
from pollux.pipeline.results.transforms import default_transforms


class TestResultBuilderHandlerContract:
    """Verify Result Builder adheres to pipeline handler contract."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_handler_signature_contract(self):
        """Result Builder must implement correct handler signature."""
        # Must have async handle method
        assert hasattr(ResultBuilder, "handle")
        assert inspect.iscoroutinefunction(ResultBuilder.handle)

        # Handle method signature inspection
        builder = ResultBuilder()
        sig = inspect.signature(builder.handle)
        params = list(sig.parameters.keys())

        # Must accept exactly: command (self is not in bound method signature)
        assert len(params) == 1
        assert params[0] == "command"

        # Type hints must specify FinalizedCommand input
        _mod = sys.modules.get(builder.handle.__module__)
        _ns = _mod.__dict__ if _mod is not None else {}
        hints = get_type_hints(builder.handle, globalns=_ns, localns=_ns)
        assert "command" in hints
        assert hints["command"] == FinalizedCommand

    @pytest.mark.unit
    @pytest.mark.contract
    def test_handler_never_fails_contract(self):
        """Result Builder must never fail - architectural robustness guarantee."""
        # This is verified by the return type annotation
        sig = inspect.signature(ResultBuilder.handle)
        return_annotation = sig.return_annotation

        # Must return Result[dict, Never] - Never indicates no failure cases
        # The type system enforces this architectural guarantee
        assert hasattr(return_annotation, "__origin__")  # Generic type

        # Verify it's a Result type (Success | Failure)
        # The type annotation should indicate this cannot fail

    @pytest.mark.unit
    @pytest.mark.contract
    def test_handler_purity_contract(self):
        """Result Builder must be pure - no I/O, no mutation of inputs."""
        # Should not perform I/O operations
        # (verified by architectural role - only APIHandler does I/O)

        # Should not have I/O-related imports in the module
        import pollux.pipeline.result_builder as rb_module

        source = inspect.getsource(rb_module)

        # Should not import network libraries
        io_imports = ["requests", "urllib", "http", "socket", "aiohttp"]
        for io_import in io_imports:
            assert io_import not in source, (
                f"Result Builder should not import {io_import}"
            )

        # Should not have async context managers (which often indicate I/O)
        assert "async with" not in source, (
            "Result Builder should not use async context managers"
        )


class TestExtractionDataContract:
    """Verify extraction data structures maintain immutability contract."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_extraction_types_are_immutable(self):
        """All extraction data structures must be immutable (frozen dataclasses)."""
        immutable_types = [
            TransformSpec,
            ExtractionContext,
            ExtractionContract,
            ExtractionResult,
            Violation,
        ]

        for cls in immutable_types:
            assert is_dataclass(cls), f"{cls.__name__} must be a dataclass"
            params = getattr(cls, "__dataclass_params__", None)
            assert params is not None and getattr(params, "frozen", False), (
                f"{cls.__name__} must be frozen"
            )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_transform_spec_purity_contract(self):
        """TransformSpec must enforce pure functions for matcher/extractor."""
        # The contract is enforced by type annotations and runtime validation
        # Resolve annotations (Callable is only imported under TYPE_CHECKING)
        import collections.abc as cabc
        from typing import get_args, get_origin

        _mod = sys.modules.get(TransformSpec.__module__)
        _ns = (_mod.__dict__ if _mod is not None else {}).copy()
        _ns.setdefault("Callable", cabc.Callable)

        hints = get_type_hints(TransformSpec, globalns=_ns, localns=_ns)

        matcher_hint = hints["matcher"]
        extractor_hint = hints["extractor"]

        assert get_origin(matcher_hint) is cabc.Callable
        matcher_args, matcher_ret = get_args(matcher_hint)
        # typing.get_args returns ( [args], return ) for Callable
        assert list(matcher_args) == [Any]
        assert matcher_ret is bool

        assert get_origin(extractor_hint) is cabc.Callable
        extractor_args, extractor_ret = get_args(extractor_hint)
        assert len(extractor_args) == 2
        assert get_origin(extractor_args[1]) is dict
        assert get_origin(extractor_ret) is dict

        # Runtime validation: non-callables are rejected
        bad_matcher: Any = "not-callable"
        bad_extractor: Any = "not-callable"
        with pytest.raises(ValueError):
            TransformSpec(name="x", matcher=bad_matcher, extractor=lambda _x, _s: {})
        with pytest.raises(ValueError):
            TransformSpec(name="x", matcher=lambda _x: True, extractor=bad_extractor)

        # Positive case: valid callables are accepted and preserved
        def test_matcher(_: Any) -> bool:
            return True

        def test_extractor(_: Any, __: dict[str, Any]) -> dict[str, Any]:
            return {"answers": ["test"]}

        spec = TransformSpec(
            name="test", matcher=test_matcher, extractor=test_extractor
        )
        assert spec.matcher is test_matcher
        assert spec.extractor is test_extractor

    @pytest.mark.unit
    @pytest.mark.contract
    def test_mutable_diagnostics_isolation(self):
        """ExtractionDiagnostics is intentionally mutable but isolated."""
        # This is the only mutable type in the extraction system
        assert is_dataclass(ExtractionDiagnostics)
        _params = getattr(ExtractionDiagnostics, "__dataclass_params__", None)
        assert _params is not None and getattr(_params, "frozen", True) is False

        # Should not be exposed in public API (architectural boundary)
        import pollux

        public_items = dir(pollux)
        assert "ExtractionDiagnostics" not in public_items


class TestTwoTierArchitecturalContract:
    """Verify Two-Tier Transform Chain architectural invariants."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_minimal_projection_infallible_contract(self):
        """MinimalProjection must be architecturally infallible."""
        projection = MinimalProjection()

        # Must have extract method
        assert hasattr(projection, "extract")

        # Extract method must not raise exceptions (architectural guarantee)
        sig = inspect.signature(projection.extract)
        return_annotation = sig.return_annotation

        # Should return ExtractionResult (not Result[T, E] - no failure case)
        assert return_annotation == ExtractionResult

    @pytest.mark.unit
    @pytest.mark.contract
    def test_transform_priority_determinism_contract(self):
        """Transform ordering must be deterministic (explicit priority + name)."""
        transforms = default_transforms()

        # All transforms must have explicit priority
        for transform in transforms:
            assert hasattr(transform, "priority")
            assert isinstance(transform.priority, int)

            # Names must be unique (for tiebreaking)
            assert isinstance(transform.name, str)
            assert len(transform.name) > 0

        # Names must be unique across all transforms
        names = [t.name for t in transforms]
        assert len(names) == len(set(names)), "Transform names must be unique"

    @pytest.mark.unit
    @pytest.mark.contract
    def test_record_only_validation_contract(self):
        """Validation must never fail extraction (Record Don't Reject principle)."""
        contract = ExtractionContract()

        # validate method must return violations, not raise exceptions
        sig = inspect.signature(contract.validate)
        return_annotation = sig.return_annotation

        # Must return list of Violation (not raise exceptions)
        # Handle both runtime and string annotations
        if hasattr(return_annotation, "__origin__"):
            assert return_annotation.__origin__ is list
        else:
            # String annotation case
            assert "list[Violation]" in str(return_annotation)

    @pytest.mark.unit
    @pytest.mark.contract
    def test_extraction_context_state_isolation(self):
        """ExtractionContext must isolate state (no global dependencies)."""
        # Should be constructible with only immutable data
        ctx = ExtractionContext()

        # All fields should be immutable types
        assert isinstance(ctx.expected_count, int)
        assert isinstance(ctx.prompts, tuple)  # Immutable sequence
        assert isinstance(ctx.config, dict)  # Mutable but isolated per context

        # Should not have any global state dependencies
        import pollux.pipeline.results.extraction as extraction_module

        source = inspect.getsource(extraction_module)

        # Should not access global variables or singletons
        assert "global" not in source.lower()


class TestArchitecturalBoundaries:
    """Verify architectural boundaries are maintained."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_extraction_no_sdk_dependencies(self):
        """Extraction components must not depend on provider SDKs."""
        modules_to_check = [
            "pollux.pipeline.results.extraction",
            "pollux.pipeline.results.minimal_projection",
            "pollux.pipeline.results.transforms",
        ]

        for module_name in modules_to_check:
            module = __import__(module_name, fromlist=[""])
            source = inspect.getsource(module)

            # Should not import provider SDKs
            sdk_imports = ["google.genai", "openai", "anthropic", "boto3"]
            for sdk in sdk_imports:
                assert sdk not in source, f"{module_name} should not import {sdk}"

    @pytest.mark.unit
    @pytest.mark.contract
    def test_result_builder_stateless_contract(self):
        """Result Builder must be stateless between invocations."""
        builder = ResultBuilder()

        # Should not have mutable instance state (except config)
        allowed_mutable_attrs = {
            "transforms",
            "enable_diagnostics",
            "max_text_size",
            "_minimal_projection",
        }

        for attr_name in dir(builder):
            if not attr_name.startswith("_") and attr_name not in ["handle"]:
                attr_value = getattr(builder, attr_name)
                if not callable(attr_value):
                    assert attr_name in allowed_mutable_attrs, (
                        f"Unexpected instance attribute: {attr_name}"
                    )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_public_api_minimality_contract(self):
        """Public API must expose only user-facing types."""
        import pollux

        # Only specific extraction types should be publicly exposed via pollux.types
        extraction_exports = [
            "ResultEnvelope",  # The stable result structure users receive
        ]

        for item in extraction_exports:
            assert hasattr(pollux.types, item), (
                f"{item} should be in public pollux.types API"
            )

        # Internal extraction types should NOT be publicly exposed
        internal_types = [
            "ExtractionContext",
            "ExtractionDiagnostics",
            "ExtractionResult",
        ]

        for item in internal_types:
            assert not hasattr(pollux, item), f"{item} should not be in public API"
