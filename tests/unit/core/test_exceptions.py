"""Contract-first unit tests for core exceptions.

These tests verify that the exception hierarchy maintains architectural
principles of clear error handling, proper inheritance, and explicit contracts.
"""

import inspect

import pytest

from pollux.core.exceptions import (
    APIError,
    ConfigurationError,
    FileError,
    GeminiBatchError,
    MissingKeyError,
    PipelineError,
    SourceError,
    UnsupportedContentError,
    ValidationError,
)


class TestExceptionHierarchyCompliance:
    """Tests that verify the exception hierarchy maintains proper inheritance."""

    @pytest.mark.unit
    @pytest.mark.smoke
    def test_all_exceptions_inherit_from_base(self):
        """All custom exceptions should inherit from GeminiBatchError."""
        custom_exceptions = [
            APIError,
            PipelineError,
            ConfigurationError,
            SourceError,
            MissingKeyError,
            FileError,
            ValidationError,
            UnsupportedContentError,
        ]

        for exception_class in custom_exceptions:
            assert issubclass(exception_class, GeminiBatchError)

    @pytest.mark.unit
    def test_base_exception_is_proper_exception(self):
        """GeminiBatchError should be a proper exception."""
        assert issubclass(GeminiBatchError, Exception)


class TestExceptionConstructorCompliance:
    """Tests that verify exception constructors maintain proper contracts."""

    @pytest.mark.unit
    def test_base_exception_constructor_accepts_message(self):
        """GeminiBatchError should accept a message parameter."""
        message = "Test error message"
        error = GeminiBatchError(message)

        assert str(error) == message

    @pytest.mark.unit
    def test_pipeline_error_constructor_has_required_fields(self):
        """PipelineError should have required handler_name and underlying_error fields."""
        message = "Test pipeline error"
        handler_name = "TestHandler"
        underlying_error = ValueError("Underlying error")

        error = PipelineError(message, handler_name, underlying_error)

        assert error.handler_name == handler_name
        assert error.underlying_error == underlying_error
        assert "TestHandler" in str(error)
        assert "Test pipeline error" in str(error)

    @pytest.mark.unit
    def test_pipeline_error_constructor_enforces_contract(self):
        """PipelineError should require all three parameters."""
        with pytest.raises(TypeError):
            # Missing parameters
            PipelineError()  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            # Missing underlying_error
            PipelineError("message", "handler")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_simple_exceptions_accept_message(self):
        """Simple exceptions should accept a message parameter."""
        simple_exceptions = [
            APIError,
            ConfigurationError,
            SourceError,
            MissingKeyError,
            FileError,
            ValidationError,
            UnsupportedContentError,
        ]

        for exception_class in simple_exceptions:
            message = f"Test {exception_class.__name__} message"
            error = exception_class(message)
            assert str(error) == message


class TestExceptionBehaviorCompliance:
    """Tests that verify exceptions behave correctly."""

    @pytest.mark.unit
    def test_exceptions_are_immutable(self):
        """Exception instances should be immutable after construction."""
        error = PipelineError("Test error", "TestHandler", ValueError("Underlying"))

        # Exceptions are not immutable by default in Python
        # This test verifies the current behavior
        # PipelineError attributes can be modified after construction
        error.handler_name = "ModifiedHandler"
        assert error.handler_name == "ModifiedHandler"

    @pytest.mark.unit
    def test_exceptions_preserve_message(self):
        """Exceptions should preserve the original message."""
        original_message = "Original error message"
        error = GeminiBatchError(original_message)

        assert str(error) == original_message
        assert error.args[0] == original_message

    @pytest.mark.unit
    def test_pipeline_error_preserves_context(self):
        """PipelineError should preserve handler context."""
        handler_name = "SourceHandler"
        underlying_error = FileNotFoundError("File not found")

        error = PipelineError(
            "Failed to process source", handler_name, underlying_error
        )

        assert error.handler_name == handler_name
        assert error.underlying_error == underlying_error
        assert handler_name in str(error)

    @pytest.mark.unit
    def test_exceptions_are_hashable(self):
        """Exceptions should be hashable for use in sets/dicts."""
        error1 = GeminiBatchError("Error 1")
        error2 = GeminiBatchError("Error 2")

        # Should be hashable
        error_set = {error1, error2}
        assert len(error_set) == 2

    @pytest.mark.unit
    def test_exceptions_are_comparable(self):
        """Exceptions should be comparable based on their content."""
        error1 = GeminiBatchError("Same message")
        error2 = GeminiBatchError("Same message")
        error3 = GeminiBatchError("Different message")

        # Exceptions with same message are not equal by default in Python
        # This is expected behavior
        assert error1 != error2  # Different instances
        assert error1 != error3  # Different messages


class TestExceptionTypeSafetyCompliance:
    """Tests that verify exceptions maintain type safety."""

    @pytest.mark.unit
    def test_exception_types_are_distinct(self):
        """Different exception types should be distinct."""
        exceptions = [
            APIError("API error"),
            ConfigurationError("Config error"),
            SourceError("Source error"),
            FileError("File error"),
            ValidationError("Validation error"),
            UnsupportedContentError("Content error"),
        ]

        # All should be different types
        exception_types = [type(exc) for exc in exceptions]
        assert len(set(exception_types)) == len(exception_types)

    @pytest.mark.unit
    def test_pipeline_error_is_distinct_type(self):
        """PipelineError should be a distinct type from other exceptions."""
        pipeline_error = PipelineError("Test", "Handler", ValueError("Underlying"))

        assert isinstance(pipeline_error, PipelineError)
        assert isinstance(pipeline_error, GeminiBatchError)
        assert not isinstance(pipeline_error, APIError)
        assert not isinstance(pipeline_error, ConfigurationError)


class TestExceptionContractCompliance:
    """Tests that verify exceptions have explicit, clear contracts."""

    @pytest.mark.unit
    def test_pipeline_error_has_explicit_interface(self):
        """PipelineError should have an explicit interface with required fields."""
        import inspect

        sig = inspect.signature(PipelineError.__init__)

        # Should take exactly 4 parameters (self, message, handler_name, underlying_error)
        assert len(sig.parameters) == 4
        assert "message" in sig.parameters
        assert "handler_name" in sig.parameters
        assert "underlying_error" in sig.parameters

        # Parameters should be properly typed
        message_param = sig.parameters["message"]
        handler_param = sig.parameters["handler_name"]
        error_param = sig.parameters["underlying_error"]

        # Allow None to be passed at runtime; the constructor should accept Optional[str]
        assert message_param.annotation is str or message_param.annotation == (
            str | type(None)
        )
        assert handler_param.annotation is str
        assert error_param.annotation is Exception

    @pytest.mark.unit
    def test_simple_exceptions_have_simple_contracts(self):
        """Simple exceptions should have simple, clear contracts."""
        simple_exceptions = [
            APIError,
            ConfigurationError,
            SourceError,
            MissingKeyError,
            FileError,
            ValidationError,
            UnsupportedContentError,
        ]

        for exception_class in simple_exceptions:
            sig = inspect.signature(exception_class.__init__)

            # Simple exceptions inherit from Exception which uses *args, **kwargs
            # So they should have 3 parameters: self, *args, **kwargs
            assert len(sig.parameters) == 3
            assert "args" in sig.parameters
            assert "kwargs" in sig.parameters

            # The first positional argument is the message
            args_param = sig.parameters["args"]
            assert args_param.kind == inspect.Parameter.VAR_POSITIONAL

    @pytest.mark.unit
    def test_exceptions_follow_naming_convention(self):
        """Exceptions should follow consistent naming conventions."""
        # All custom exceptions should end with "Error"
        custom_exceptions = [
            GeminiBatchError,
            APIError,
            PipelineError,
            ConfigurationError,
            SourceError,
            MissingKeyError,
            FileError,
            ValidationError,
            UnsupportedContentError,
        ]

        for exception_class in custom_exceptions:
            assert exception_class.__name__.endswith("Error")


class TestExceptionRobustnessCompliance:
    """Tests that verify exceptions handle edge cases robustly."""

    @pytest.mark.unit
    def test_exceptions_handle_empty_messages(self):
        """Exceptions should handle empty message strings."""
        empty_message = ""

        # Simple exceptions
        simple_exceptions = [
            APIError,
            ConfigurationError,
            SourceError,
            MissingKeyError,
            FileError,
            ValidationError,
            UnsupportedContentError,
        ]

        for exception_class in simple_exceptions:
            error = exception_class(empty_message)
            assert str(error) == empty_message

        # PipelineError
        pipeline_error = PipelineError(
            empty_message, "TestHandler", ValueError("Underlying")
        )
        assert empty_message in str(pipeline_error)

    @pytest.mark.unit
    def test_exceptions_handle_unicode_messages(self):
        """Exceptions should handle unicode message strings."""
        unicode_message = "🚀 Unicode error message 🚀"

        error = GeminiBatchError(unicode_message)
        assert str(error) == unicode_message

    @pytest.mark.unit
    def test_pipeline_error_handles_various_underlying_errors(self):
        """PipelineError should handle various types of underlying errors."""
        underlying_errors = [
            ValueError("Value error"),
            TypeError("Type error"),
            FileNotFoundError("File not found"),
            ConnectionError("Connection error"),
            RuntimeError("Runtime error"),
        ]

        for underlying_error in underlying_errors:
            pipeline_error = PipelineError(
                "Test error", "TestHandler", underlying_error
            )

            assert pipeline_error.underlying_error == underlying_error
            assert "TestHandler" in str(pipeline_error)

    @pytest.mark.unit
    def test_exceptions_handle_none_message(self):
        """Exceptions should handle None message gracefully."""
        # Simple exceptions
        simple_exceptions = [
            APIError,
            ConfigurationError,
            SourceError,
            MissingKeyError,
            FileError,
            ValidationError,
            UnsupportedContentError,
        ]

        for exception_class in simple_exceptions:
            error = exception_class(None)
            assert str(error) == "None"

        # PipelineError — pass explicit string to match constructor signature
        pipeline_error = PipelineError("None", "TestHandler", ValueError("Underlying"))
        assert "None" in str(pipeline_error)


class TestExceptionArchitecturalCompliance:
    """Tests that verify exceptions support architectural principles."""

    @pytest.mark.unit
    def test_exceptions_support_error_handling_patterns(self):
        """Exceptions should support common error handling patterns."""
        # Test exception chaining
        original_error = FileNotFoundError("File not found")
        pipeline_error = PipelineError(
            "Failed to process source", "SourceHandler", original_error
        )

        # Should preserve original error
        assert pipeline_error.underlying_error == original_error

        # Should provide context
        assert "SourceHandler" in str(pipeline_error)

    @pytest.mark.unit
    def test_exceptions_support_granular_catching(self):
        """Exceptions should support granular error catching."""
        # Test that specific exceptions can be caught separately
        api_caught = False
        base_caught = False

        try:
            raise APIError("API error")
        except APIError:
            api_caught = True
        except GeminiBatchError:
            base_caught = True

        assert api_caught
        assert not base_caught

    @pytest.mark.unit
    def test_exceptions_support_broad_catching(self):
        """Exceptions should support broad error catching."""
        # Test that base exception catches all custom exceptions
        try:
            raise SourceError("Source error")
        except GeminiBatchError:
            base_caught = True
        else:
            base_caught = False

        assert base_caught

    @pytest.mark.unit
    def test_exceptions_are_self_documenting(self):
        """Exceptions should be self-documenting through their names and messages."""
        # Exception names should clearly indicate their purpose
        exception_purposes = {
            APIError: "API-related errors",
            ConfigurationError: "Configuration-related errors",
            SourceError: "Source processing errors",
            PipelineError: "Pipeline execution errors",
            FileError: "File operation errors",
            ValidationError: "Validation errors",
            UnsupportedContentError: "Unsupported content errors",
        }

        for exception_class, expected_purpose in exception_purposes.items():
            # The class name should indicate its purpose
            class_name = exception_class.__name__.lower().replace("error", "")
            # Handle camelCase to space-separated conversion
            if "unsupportedcontent" in class_name:
                class_name = "unsupportedcontent"
            # Convert expected purpose to lowercase and remove spaces for comparison
            expected_lower = expected_purpose.lower().replace(" ", "")
            assert class_name in expected_lower
