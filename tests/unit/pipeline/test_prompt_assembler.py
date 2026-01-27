"""Tests for prompt assembler functionality."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock

import pytest

from pollux.config import resolve_config
from pollux.core.exceptions import ConfigurationError
from pollux.core.types import (
    InitialCommand,
    PromptBundle,
    ResolvedCommand,
    Source,
)
from pollux.pipeline.prompts import assemble_prompts

pytestmark = pytest.mark.unit


class TestPromptAssemblerBasic:
    """Test basic prompt assembly functionality."""

    def test_simple_prompt_assembly_no_config(self):
        """Test basic prompt assembly with no special configuration."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("Hello, world!",),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        bundle = assemble_prompts(command)

        assert isinstance(bundle, PromptBundle)
        assert bundle.user == ("Hello, world!",)
        assert bundle.system is None
        assert bundle.provenance["user_from"] == "initial"
        assert bundle.provenance["has_sources"] is False

    def test_multiple_prompts_preserved(self):
        """Test that multiple user prompts are preserved in order."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("First prompt", "Second prompt", "Third prompt"),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        bundle = assemble_prompts(command)

        assert bundle.user == ("First prompt", "Second prompt", "Third prompt")
        assert bundle.provenance["user_from"] == "initial"

    def test_empty_prompts_raises_error(self):
        """Test that empty prompts raises ConfigurationError."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=(),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        with pytest.raises(ConfigurationError, match="No prompts provided"):
            assemble_prompts(command)


class TestPromptAssemblerInlineConfig:
    """Test prompt assembly with inline configuration."""

    def test_inline_system_instruction(self):
        """Test system instruction from inline config."""
        config = resolve_config(
            overrides={"prompts.system": "You are a helpful assistant."}
        )
        initial = InitialCommand(
            sources=(),
            prompts=("Hello",),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        bundle = assemble_prompts(command)

        assert bundle.system == "You are a helpful assistant."
        assert bundle.provenance["system_from"] == "inline"
        assert bundle.provenance["system_len"] == len("You are a helpful assistant.")

    def test_prefix_suffix_applied(self):
        """Test prefix and suffix are applied to user prompts."""
        config = resolve_config(
            overrides={
                "prompts.prefix": "Answer concisely: ",
                "prompts.suffix": " Please be brief.",
            }
        )
        initial = InitialCommand(
            sources=(),
            prompts=("What is AI?", "How does ML work?"),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        bundle = assemble_prompts(command)

        expected_user = (
            "Answer concisely: What is AI? Please be brief.",
            "Answer concisely: How does ML work? Please be brief.",
        )
        assert bundle.user == expected_user

    def test_prefix_only(self):
        """Test prefix only configuration."""
        config = resolve_config(
            overrides={
                "prompts.prefix": "Q: ",
            }
        )
        initial = InitialCommand(
            sources=(),
            prompts=("What is 2+2?",),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        bundle = assemble_prompts(command)

        assert bundle.user == ("Q: What is 2+2?",)


class TestPromptAssemblerSourceAwareness:
    """Test source-aware guidance functionality."""

    def test_sources_block_with_system_instruction(self):
        """Test sources block appended to system instruction."""
        config = resolve_config(
            overrides={
                "prompts.system": "You are helpful.",
                "prompts.sources_policy": "append_or_replace",
                "prompts.sources_block": "Use the provided sources if relevant.",
            }
        )
        initial = InitialCommand(
            sources=(Source.from_text("doc.txt"),),
            prompts=("Summarize",),
            config=config,
        )
        # Mock resolved sources
        mock_source = MagicMock()
        command = ResolvedCommand(initial=initial, resolved_sources=(mock_source,))

        bundle = assemble_prompts(command)

        expected_system = "You are helpful.\n\nUse the provided sources if relevant."
        assert bundle.system == expected_system
        assert bundle.provenance["has_sources"] is True

    def test_sources_block_without_system_instruction(self):
        """Test sources block becomes system instruction when no system provided."""
        config = resolve_config(
            overrides={
                "prompts.sources_policy": "append_or_replace",
                "prompts.sources_block": "Use the provided sources.",
            }
        )
        initial = InitialCommand(
            sources=(Source.from_text("doc.txt"),),
            prompts=("Analyze",),
            config=config,
        )
        mock_source = MagicMock()
        command = ResolvedCommand(initial=initial, resolved_sources=(mock_source,))

        bundle = assemble_prompts(command)

        assert bundle.system == "Use the provided sources."
        assert bundle.provenance["system_from"] == "sources_block"

    def test_sources_block_not_applied_without_sources(self):
        """Test sources block not applied when no sources present."""
        config = resolve_config(
            overrides={
                "prompts.system": "You are helpful.",
                "prompts.sources_policy": "append_or_replace",
                "prompts.sources_block": "Use sources.",
            }
        )
        initial = InitialCommand(
            sources=(),
            prompts=("Hello",),
            config=config,
        )
        command = ResolvedCommand(initial=initial, resolved_sources=())

        bundle = assemble_prompts(command)

        assert bundle.system == "You are helpful."  # No sources block appended
        assert bundle.provenance["has_sources"] is False

    def test_sources_block_not_applied_when_disabled(self):
        """Test sources block not applied when apply_if_sources=False."""
        config = resolve_config(
            overrides={
                "prompts.system": "You are helpful.",
                "prompts.sources_policy": "never",
                "prompts.sources_block": "Use sources.",
            }
        )
        initial = InitialCommand(
            sources=(Source.from_text("doc.txt"),),
            prompts=("Hello",),
            config=config,
        )
        mock_source = MagicMock()
        command = ResolvedCommand(initial=initial, resolved_sources=(mock_source,))

        bundle = assemble_prompts(command)

        assert bundle.system == "You are helpful."  # No sources block appended


class TestPromptAssemblerFileInputs:
    """Test file-based prompt inputs."""

    def test_system_file_precedence(self):
        """Test system_file used when inline system not provided."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("System from file.")
            system_file_path = f.name

        try:
            config = resolve_config(
                overrides={
                    "prompts.system_file": system_file_path,
                }
            )
            initial = InitialCommand(
                sources=(),
                prompts=("Hello",),
                config=config,
            )
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)

            assert bundle.system == "System from file."
            assert bundle.provenance["system_from"] == "system_file"
            assert bundle.provenance["system_file"] == system_file_path
        finally:
            Path(system_file_path).unlink()

    def test_inline_system_overrides_system_file(self):
        """Test inline system takes precedence over system_file."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("System from file.")
            system_file_path = f.name

        try:
            config = resolve_config(
                overrides={
                    "prompts.system": "Inline system.",
                    "prompts.system_file": system_file_path,
                }
            )
            initial = InitialCommand(
                sources=(),
                prompts=("Hello",),
                config=config,
            )
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)

            assert bundle.system == "Inline system."
            assert bundle.provenance["system_from"] == "inline"
        finally:
            Path(system_file_path).unlink()

    def test_user_file_when_no_initial_prompts(self):
        """Test user_file used when initial.prompts is empty."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("User prompt from file.")
            user_file_path = f.name

        try:
            config = resolve_config(
                overrides={
                    "prompts.user_file": user_file_path,
                }
            )
            initial = InitialCommand(
                sources=(),
                prompts=(),  # Empty prompts
                config=config,
            )
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)

            assert bundle.user == ("User prompt from file.",)
            assert bundle.provenance["user_from"] == "user_file"
            assert bundle.provenance["user_file"] == user_file_path
        finally:
            Path(user_file_path).unlink()

    def test_initial_prompts_ignore_user_file(self):
        """Test user_file is ignored when initial.prompts exists."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("User prompt from file.")
            user_file_path = f.name

        try:
            config = resolve_config(
                overrides={
                    "prompts.user_file": user_file_path,
                }
            )
            initial = InitialCommand(
                sources=(),
                prompts=("Initial prompt",),
                config=config,
            )
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)

            assert bundle.user == ("Initial prompt",)
            assert bundle.provenance["user_from"] == "initial"
        finally:
            Path(user_file_path).unlink()

    def test_file_reading_options(self):
        """Test file reading with custom encoding and strip options."""
        with NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Content with newlines\n\n")
            file_path = f.name

        try:
            # Test with strip=True (default)
            config = resolve_config(
                overrides={
                    "prompts.system_file": file_path,
                    "prompts.encoding": "utf-8",
                    "prompts.strip": True,
                }
            )
            initial = InitialCommand(sources=(), prompts=("test",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)
            assert (
                bundle.system == "Content with newlines"
            )  # Trailing newlines stripped

            # Test with strip=False
            config = resolve_config(
                overrides={
                    "prompts.system_file": file_path,
                    "prompts.strip": False,
                }
            )
            initial = InitialCommand(sources=(), prompts=("test",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)
            assert bundle.system == "Content with newlines\n\n"  # Newlines preserved
        finally:
            Path(file_path).unlink()


class TestPromptAssemblerErrorHandling:
    """Test error handling in prompt assembly."""

    def test_missing_system_file_raises_error(self):
        """Test missing system file raises ConfigurationError."""
        config = resolve_config(
            overrides={
                "prompts.system_file": "/nonexistent/file.txt",
            }
        )
        initial = InitialCommand(sources=(), prompts=("test",), config=config)
        command = ResolvedCommand(initial=initial, resolved_sources=())

        with pytest.raises(ConfigurationError, match="not found"):
            assemble_prompts(command)

    def test_missing_user_file_raises_error(self):
        """Test missing user file raises ConfigurationError."""
        config = resolve_config(
            overrides={
                "prompts.user_file": "/nonexistent/file.txt",
            }
        )
        initial = InitialCommand(sources=(), prompts=(), config=config)
        command = ResolvedCommand(initial=initial, resolved_sources=())

        with pytest.raises(ConfigurationError, match="not found"):
            assemble_prompts(command)

    def test_file_size_limit_exceeded(self):
        """Test file size limit enforcement."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 1000)  # 1000 bytes
            large_file_path = f.name

        try:
            config = resolve_config(
                overrides={
                    "prompts.system_file": large_file_path,
                    "prompts.max_bytes": 500,  # Limit to 500 bytes
                }
            )
            initial = InitialCommand(sources=(), prompts=("test",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            with pytest.raises(ConfigurationError, match="too large"):
                assemble_prompts(command)
        finally:
            Path(large_file_path).unlink()

    def test_encoding_error_handling(self):
        """Test encoding error handling."""
        # Create a file with non-UTF-8 content
        test_file = Path("/tmp/test_encoding.txt")
        test_file.write_bytes(b"\xff\xfe\x00\x48")  # Invalid UTF-8

        try:
            config = resolve_config(
                overrides={
                    "prompts.system_file": "/tmp/test_encoding.txt",
                    "prompts.encoding": "utf-8",
                }
            )
            initial = InitialCommand(sources=(), prompts=("test",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            with pytest.raises(ConfigurationError, match="encoding issue"):
                assemble_prompts(command)
        finally:
            Path("/tmp/test_encoding.txt").unlink()


class TestPromptAssemblerBuilderHook:
    """Test advanced builder hook functionality."""

    def test_builder_hook_basic_usage(self):
        """Test basic builder hook functionality."""

        # Create a simple builder function
        def test_builder(_command):
            return PromptBundle(
                user=("Custom prompt",),
                system="Custom system",
                provenance={"builder_used": True},
            )

        # Mock the import
        import sys
        import types

        test_module = types.ModuleType("test_module")
        test_module.test_builder = test_builder  # type: ignore
        sys.modules["test_module"] = test_module

        try:
            config = resolve_config(
                overrides={
                    "prompts.builder": "test_module:test_builder",
                }
            )
            initial = InitialCommand(sources=(), prompts=("original",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)

            assert bundle.user == ("Custom prompt",)
            assert bundle.system == "Custom system"
            assert bundle.provenance["builder_used"] is True
        finally:
            del sys.modules["test_module"]

    def test_builder_hook_count_invariant_not_enforced(self):
        """Test that builder hook does not enforce count invariant (trusts type system)."""

        def bad_builder(_command):
            # Would violate count invariant in old system, but new system trusts the builder
            return PromptBundle(
                user=("Too", "Many", "Prompts"),  # 3 instead of 1
                system=None,
                provenance={},
            )

        import sys
        import types

        test_module = types.ModuleType("test_module")
        test_module.bad_builder = bad_builder  # type: ignore
        sys.modules["test_module"] = test_module

        try:
            config = resolve_config(
                overrides={
                    "prompts.builder": "test_module:bad_builder",
                }
            )
            initial = InitialCommand(sources=(), prompts=("original",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            # Should succeed now - we trust the builder function
            bundle = assemble_prompts(command)
            assert bundle.user == ("Too", "Many", "Prompts")
        finally:
            del sys.modules["test_module"]

    def test_builder_hook_import_error(self):
        """Test builder hook import error handling."""
        config = resolve_config(
            overrides={
                "prompts.builder": "nonexistent_module:function",
            }
        )
        initial = InitialCommand(sources=(), prompts=("test",), config=config)
        command = ResolvedCommand(initial=initial, resolved_sources=())

        with pytest.raises(ConfigurationError, match=r"Builder.*failed"):
            assemble_prompts(command)

    def test_builder_hook_invalid_path(self):
        """Test builder hook invalid path format."""
        config = resolve_config(
            overrides={
                "prompts.builder": "invalid_path_format",
            }
        )
        initial = InitialCommand(sources=(), prompts=("test",), config=config)
        command = ResolvedCommand(initial=initial, resolved_sources=())

        with pytest.raises(ConfigurationError, match="Invalid builder path"):
            assemble_prompts(command)

    def test_builder_hook_wrong_return_type(self):
        """Test builder hook wrong return type handling."""

        def wrong_type_builder(_command):
            return "Not a PromptBundle"

        import sys
        import types

        test_module = types.ModuleType("test_module")
        test_module.wrong_type_builder = wrong_type_builder  # type: ignore
        sys.modules["test_module"] = test_module

        try:
            config = resolve_config(
                overrides={
                    "prompts.builder": "test_module:wrong_type_builder",
                }
            )
            initial = InitialCommand(sources=(), prompts=("test",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            with pytest.raises(
                ConfigurationError, match=r"returned.*expected PromptBundle"
            ):
                assemble_prompts(command)
        finally:
            del sys.modules["test_module"]


class TestPromptAssemblerTelemetry:
    """Test telemetry and hints generation."""

    def test_telemetry_hints_basic(self):
        """Test basic telemetry hints are generated."""
        config = resolve_config(
            overrides={
                "prompts.system": "Test system",
            }
        )
        initial = InitialCommand(
            sources=(Source.from_text("doc.txt"),),
            prompts=("Hello", "World"),
            config=config,
        )
        mock_source = MagicMock()
        command = ResolvedCommand(initial=initial, resolved_sources=(mock_source,))

        bundle = assemble_prompts(command)

        assert bundle.provenance["user_from"] == "initial"
        assert bundle.provenance["system_from"] == "inline"
        assert bundle.provenance["has_sources"] is True
        assert bundle.provenance["system_len"] == len("Test system")
        assert bundle.provenance["user_total_len"] == len("Hello") + len("World")

    def test_telemetry_hints_file_paths(self):
        """Test file paths included in telemetry hints."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("System content")
            system_file_path = f.name

        try:
            config = resolve_config(
                overrides={
                    "prompts.system_file": system_file_path,
                }
            )
            initial = InitialCommand(sources=(), prompts=("test",), config=config)
            command = ResolvedCommand(initial=initial, resolved_sources=())

            bundle = assemble_prompts(command)

            assert bundle.provenance["system_file"] == system_file_path
            assert bundle.provenance["system_from"] == "system_file"
        finally:
            Path(system_file_path).unlink()
