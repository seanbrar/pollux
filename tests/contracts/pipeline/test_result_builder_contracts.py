"""Contract tests for Result Builder architectural compliance.

These tests verify that the Result Builder implementation adheres to the
architectural contracts defined in the Command Pipeline and Two-Tier Transform
Chain specifications, rather than testing specific input/output behaviors.
"""

import inspect

import pytest

from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.results.extraction import (
    ExtractionContext,
)
from pollux.pipeline.results.transforms import default_transforms


class TestResultBuilderHandlerContract:
    """Verify Result Builder adheres to pipeline handler contract."""

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


class TestTwoTierArchitecturalContract:
    """Verify Two-Tier Transform Chain architectural invariants."""

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
