from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pollux.core.exceptions import InvariantViolationError
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_types import Exchange

from ._builders import make_state

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_engine_appends_with_expected_version(
    mock_executor: MagicMock, mock_result: dict[str, object]
) -> None:
    # Arrange a store that records expected_version used during append
    store = MagicMock()
    init_state = make_state(version=3)
    store.load = AsyncMock(return_value=init_state)
    store.append = AsyncMock()

    # Executor fixture returns a canonical result; tailor it for this test
    mock_executor.execute = AsyncMock(
        return_value={
            **mock_result,
            "answers": ["ok"],
            "extraction_method": "stub",
            "confidence": 1.0,
        }
    )

    engine = ConversationEngine(mock_executor, store)

    # Act
    ex = await engine.ask("conv-1", "Hi?")

    # Assert new exchange and OCC version used
    assert isinstance(ex, Exchange)
    store.append.assert_awaited_once()
    assert store.append.await_args is not None
    assert store.append.await_args.kwargs.get("expected_version") == init_state.version


@pytest.mark.asyncio
async def test_engine_bubbles_invalid_envelope_error(mock_executor: MagicMock) -> None:
    # Store returns an empty state
    store = MagicMock()
    store.load = AsyncMock(return_value=make_state())
    store.append = AsyncMock()

    # Executor returns an invalid envelope (missing required keys)
    mock_executor.execute = AsyncMock(return_value={"unexpected": True})

    engine = ConversationEngine(mock_executor, store)

    with pytest.raises(InvariantViolationError):
        await engine.ask("conv-err", "boom")
