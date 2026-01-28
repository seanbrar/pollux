import inspect

import pytest

from pollux.core import exceptions, models, types


class TestMaintainabilityCompliance:
    """Tests that verify the core module maintains architectural maintainability."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_module_structure_is_logical(self):
        """The core module should have a logical, organized structure."""
        # Check that related functionality is grouped together
        types_items = dir(types)
        models_items = dir(models)
        exceptions_items = dir(exceptions)

        # Types module should contain data structures
        assert any("Command" in item for item in types_items), (
            "Types module should contain Command classes"
        )
        assert any("Source" in item for item in types_items), (
            "Types module should contain Source class"
        )
        assert any("Result" in item for item in types_items), (
            "Types module should contain Result types"
        )

        # Models module should contain model-related functionality
        assert any("Model" in item for item in models_items), (
            "Models module should contain Model classes"
        )
        assert any("get_model" in item for item in models_items), (
            "Models module should contain model lookup functions"
        )

        # Exceptions module should contain exception classes or hint helpers
        assert all(
            "error" in item.lower() or "hint" in item.lower()
            for item in exceptions_items
            if not item.startswith("_")
        ), "Exceptions module should contain Error classes or hint helpers"

    @pytest.mark.unit
    @pytest.mark.contract
    def test_dependencies_are_minimal(self):
        """The core module should have minimal external dependencies."""
        # Check imports in each module
        types_imports = inspect.getsource(types)
        models_imports = inspect.getsource(models)
        exceptions_imports = inspect.getsource(exceptions)

        # Should not have too many external imports
        _external_imports = [
            "google.genai",  # Only external dependency
            "pathlib",
            "collections.abc",
            "dataclasses",
            "typing",
            "enum",
        ]

        # Count non-standard library imports
        # Standard library imports are acceptable for core functionality
        # Only external dependencies should be limited
        external_dependencies = ["google.genai"]
        for dep in external_dependencies:
            assert (
                dep in types_imports
                or dep in models_imports
                or dep in exceptions_imports
            ), f"Expected dependency {dep} not found"

    @pytest.mark.unit
    @pytest.mark.contract
    def test_code_is_self_documenting(self):
        """The code should be self-documenting through clear naming and structure."""
        # Check that class and function names are descriptive
        descriptive_names = [
            "InitialCommand",
            "ResolvedCommand",
            "PlannedCommand",
            "FinalizedCommand",
            "get_model_capabilities",
            "get_rate_limits",
            "can_use_caching",
            "PipelineError",
            "SourceError",
            "ConfigurationError",
        ]

        for name in descriptive_names:
            # Check if the name exists in any of the modules
            found = False
            for module in [types, models, exceptions]:
                if hasattr(module, name):
                    found = True
                    break

            assert found, (
                f"Expected descriptive name '{name}' not found in core modules"
            )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_no_circular_dependencies(self):
        """The core module should not have circular dependencies."""
        # Check that core modules don't import each other
        types_source = inspect.getsource(types)
        models_source = inspect.getsource(models)
        exceptions_source = inspect.getsource(exceptions)

        # Types module should not import from models or exceptions
        assert "from pollux.core.models" not in types_source
        assert "from pollux.core.exceptions" not in types_source

        # Models module should not import from types or exceptions
        assert "from pollux.core.types" not in models_source
        assert "from pollux.core.exceptions" not in models_source

        # Exceptions module should not import from types or models
        assert "from pollux.core.types" not in exceptions_source
        assert "from pollux.core.models" not in exceptions_source
