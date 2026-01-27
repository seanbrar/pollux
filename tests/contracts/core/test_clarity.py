import inspect
from typing import TYPE_CHECKING, Any, cast

import pytest

from pollux.core import exceptions, models, types

if TYPE_CHECKING:
    from collections.abc import Callable


class TestClarityCompliance:
    """Tests that verify the core module maintains architectural clarity."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_all_public_items_have_docstrings(self):
        """All public classes and functions should have docstrings."""
        modules = [types, models, exceptions]

        for module in modules:
            public_items = [
                name
                for name in dir(module)
                if not name.startswith("_")
                and not inspect.ismodule(getattr(module, name))
            ]

            for item_name in public_items:
                item = getattr(module, item_name)

                if inspect.isclass(item) or inspect.isfunction(item):
                    # Skip imported types that don't have docstrings
                    if item_name in ["Callable", "Any", "Literal", "TypeVar", "Path"]:
                        continue
                    assert item.__doc__ is not None, (
                        f"{module.__name__}.{item_name} missing docstring"
                    )
                    assert len(item.__doc__.strip()) > 10, (
                        f"{module.__name__}.{item_name} has short docstring"
                    )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_type_hints_are_comprehensive(self):
        """All public functions should have comprehensive type hints."""
        functions = [
            models.get_model_capabilities,
            models.get_rate_limits,
            models.can_use_caching,
        ]

        for func in functions:
            # Cast to Callable for static analysis when using inspect.signature
            sig = inspect.signature(cast("Callable[..., Any]", func))

            # All parameters should have type hints
            for param_name, param in sig.parameters.items():
                assert param.annotation != inspect.Parameter.empty, (
                    f"{func.__name__}.{param_name} missing type hint"
                )

            # Return type should be specified
            assert sig.return_annotation != inspect.Signature.empty, (
                f"{func.__name__} missing return type"
            )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_dataclass_fields_have_type_hints(self):
        """All dataclass fields should have type hints."""
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
            annotations = getattr(cls, "__annotations__", {})
            assert len(annotations) > 0, f"{cls.__name__} has no type annotations"

            # All fields should have annotations
            for field_name in annotations:
                assert annotations[field_name] is not None, (
                    f"{cls.__name__}.{field_name} has None annotation"
                )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_naming_conventions_are_consistent(self):
        """Naming conventions should be consistent throughout the module."""
        # Check class naming (PascalCase)
        classes = [
            types.Success,
            types.Failure,
            types.Turn,
            types.Source,
            types.InitialCommand,
            types.ResolvedCommand,
            models.APITier,
            models.RateLimits,
            models.CachingCapabilities,
            models.ModelCapabilities,
            exceptions.GeminiBatchError,
            exceptions.APIError,
            exceptions.PipelineError,
        ]

        for cls in classes:
            name = cls.__name__
            assert name[0].isupper(), f"{name} should start with uppercase"
            assert "_" not in name or name.isupper(), f"{name} should use PascalCase"

        # Check function naming (snake_case)
        functions = [
            models.get_model_capabilities,
            models.get_rate_limits,
            models.can_use_caching,
        ]

        for func in functions:
            name = func.__name__
            assert name.islower(), f"{name} should be lowercase"
            assert " " not in name, f"{name} should not contain spaces"
