"""Extensions-focused fixtures shared across test types.

Provides lightweight executors and canonical results for conversation
extension tests. Prefer these over ad-hoc local fixtures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pollux.config import resolve_config
from pollux.executor import create_executor


@pytest.fixture
def mock_executor():
    """Mock GeminiExecutor for conversation facade and flow tests (fast)."""
    executor = MagicMock()
    executor.config = MagicMock()
    executor.config.to_frozen.return_value = MagicMock()
    # Provide a default async execute to avoid boilerplate in tests
    executor.execute = AsyncMock(
        return_value={
            "status": "ok",
            "answers": ["stub"],
            "metrics": {},
            "usage": {},
        }
    )
    return executor


@pytest.fixture
def mock_result():
    """Canonical successful execution result payload."""
    return {
        "status": "ok",
        "answers": ["This is a test response."],
        "metrics": {
            "token_validation": {
                "estimated_min": 10,
                "estimated_max": 50,
                "actual": 25,
                "in_range": True,
            }
        },
        "usage": {"total_tokens": 25},
    }


@pytest.fixture
def executor():
    """Production-style executor with default mocked outputs (offline, no API)."""
    config = resolve_config()
    return create_executor(config)
