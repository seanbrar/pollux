"""Architectural contract tests.

These tests verify machine-checkable invariants that span modules. If a test
here fails, investigate the architecture—don't adjust the assertion.

Contracts are grouped by subsystem:
- ConfigContracts: Configuration resolution, precedence, security
- PipelineContracts: Executor invariants, result envelope guarantees
- ExecutionOptionsContracts: Options equivalence (None vs empty)
- ExtensionsContracts: Conversation store, persistence guarantees
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import patch

import pytest

from pollux.config import resolve_config
from pollux.config.core import FrozenConfig, audit_text
from pollux.core.exceptions import (
    ConfigurationError,
    InvariantViolationError,
    PolluxError,
)
from pollux.core.execution_options import ExecutionOptions
from pollux.core.models import APITier
from pollux.core.types import InitialCommand, Result, Success
from pollux.executor import GeminiExecutor, create_executor
from pollux.extensions import Exchange
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_store import JSONStore
from pollux.pipeline.base import BaseAsyncHandler

pytestmark = pytest.mark.contract


# =============================================================================
# Config Contracts
# =============================================================================


class TestConfigContracts:
    """Configuration system architectural invariants."""

    def test_error_handling_is_explicit_for_missing_api_key(self) -> None:
        """Contract: use_real_api=True without api_key raises ConfigurationError."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            resolve_config(overrides={"use_real_api": True})

        assert "api_key" in str(exc_info.value).lower()

    def test_precedence_order_invariant(self) -> None:
        """Invariant: Precedence order must be overrides > env > project > home > defaults."""
        from pollux.config import Origin

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            project_file = temp_path / "pyproject.toml"
            project_file.write_text(
                '[tool.pollux]\nmodel = "project-model"\nttl_seconds = 100'
            )

            home_file = temp_path / "home_config.toml"
            home_file.write_text(
                '[tool.pollux]\nmodel = "home-model"\nttl_seconds = 200\nenable_caching = true'
            )

            env_vars = {
                "GEMINI_API_KEY": "env_key",
                "POLLUX_MODEL": "env-model",
                "POLLUX_PYPROJECT_PATH": str(project_file),
                "POLLUX_CONFIG_HOME": str(home_file),
            }

            with (
                patch.dict(os.environ, env_vars, clear=True),
                patch(
                    "pollux.config.loaders.load_home",
                    return_value={
                        "model": "home-model",
                        "ttl_seconds": 200,
                        "enable_caching": True,
                    },
                ),
                patch(
                    "pollux.config.loaders.load_env",
                    return_value={"model": "env-model", "api_key": "env_key"},
                ),
            ):
                result, sources = resolve_config(
                    overrides={"api_key": "prog_key"}, explain=True
                )

                assert result.api_key == "prog_key"
                assert sources["api_key"].origin == Origin.OVERRIDES
                assert result.model == "env-model"
                assert sources["model"].origin == Origin.ENV
                assert result.ttl_seconds == 100
                assert sources["ttl_seconds"].origin == Origin.PROJECT
                assert result.enable_caching is True
                assert sources["enable_caching"].origin == Origin.HOME


class TestConfigSecurityContracts:
    """Security invariants for the configuration system."""

    @pytest.mark.security
    def test_api_key_never_in_string_representation(self) -> None:
        """Security: API key must never appear in string representations."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            cfg = resolve_config()

            cfg_str = str(cfg)
            cfg_repr = repr(cfg)

            assert secret_key not in cfg_str
            assert secret_key not in cfg_repr

    @pytest.mark.security
    def test_api_key_redacted_in_audit_repr(self) -> None:
        """Security: API key must be redacted in audit representation."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            cfg, origin = resolve_config(explain=True)

            redacted_text = audit_text(cfg, origin)
            assert secret_key not in redacted_text

            redacted_repr_lower = redacted_text.lower()
            assert any(
                indicator in redacted_repr_lower
                for indicator in ["***", "[redacted]", "hidden", "secret"]
            )


# =============================================================================
# Pipeline Contracts
# =============================================================================


class _PassThroughStage(BaseAsyncHandler[Any, Any, PolluxError]):
    """A minimal handler that returns input unchanged, violating envelope invariant."""

    async def handle(self, command: Any) -> Result[Any, PolluxError]:
        return Success(command)


def _minimal_config() -> FrozenConfig:
    return FrozenConfig(
        model="gemini-2.0-flash",
        api_key=None,
        use_real_api=False,
        enable_caching=False,
        ttl_seconds=0,
        telemetry_enabled=False,
        tier=APITier.FREE,
        provider="gemini",
        extra={},
        request_concurrency=6,
    )


def _minimal_command(cfg: FrozenConfig | None = None) -> InitialCommand:
    return InitialCommand(
        sources=(), prompts=("Hello",), config=cfg or _minimal_config()
    )


class TestPipelineContracts:
    """Pipeline execution architectural invariants."""

    @pytest.mark.asyncio
    async def test_invariant_violation_when_no_result_envelope_produced(self) -> None:
        """Contract: Pipeline must produce a ResultEnvelope; violations raise InvariantViolationError."""
        executor = GeminiExecutor(
            _minimal_config(), pipeline_handlers=[_PassThroughStage()]
        )

        with pytest.raises(InvariantViolationError) as ei:
            await executor.execute(_minimal_command())

        assert "ResultEnvelope" in str(ei.value)
        assert getattr(ei.value, "stage_name", None) == "_PassThroughStage"


# =============================================================================
# Execution Options Contracts
# =============================================================================


class TestExecutionOptionsContracts:
    """Verify options=None produces identical behavior to default/no options."""

    @pytest.mark.asyncio
    async def test_end_to_end_no_op_guarantee(self) -> None:
        """End-to-end execution should be identical with options=None vs default options."""
        executor = create_executor()

        cmd_none = InitialCommand(
            sources=(), prompts=("e2e test",), config=resolve_config(), options=None
        )

        cmd_empty = InitialCommand(
            sources=(),
            prompts=("e2e test",),
            config=resolve_config(),
            options=ExecutionOptions(),
        )

        result_none = await executor.execute(cmd_none)
        result_empty = await executor.execute(cmd_empty)

        assert result_none["status"] == result_empty["status"]
        assert result_none["extraction_method"] == result_empty["extraction_method"]
        assert isinstance(result_none["answers"], list)
        assert isinstance(result_empty["answers"], list)


# =============================================================================
# Extensions Contracts
# =============================================================================


class TestExtensionsContracts:
    """Extension module architectural invariants."""

    @pytest.mark.asyncio
    async def test_json_store_occ_and_engine(self, tmp_path: Path) -> None:
        """Contract: JSONStore uses optimistic concurrency control."""
        executor = create_executor()
        store_path = tmp_path / "store.json"
        store = JSONStore(str(store_path))
        engine = ConversationEngine(executor, store)

        conv_id = "session-1"
        ex = await engine.ask(conv_id, "Hello?")
        assert isinstance(ex.assistant, str)

        state = await store.load(conv_id)
        assert state.version == 1

        # Simulate stale append (expected_version=0) -> OCC conflict
        with pytest.raises(RuntimeError):
            await store.append(
                conv_id, expected_version=0, ex=Exchange("stale", "", error=False)
            )
