from __future__ import annotations

import pytest

from pollux.executor import create_executor
from pollux.extensions import Exchange
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_store import JSONStore


@pytest.mark.contract
@pytest.mark.asyncio
async def test_json_store_occ_and_engine(tmp_path):
    executor = create_executor()
    store_path = tmp_path / "store.json"
    store = JSONStore(str(store_path))
    engine = ConversationEngine(executor, store)

    conv_id = "session-1"
    # First turn via engine
    ex = await engine.ask(conv_id, "Hello?")
    assert isinstance(ex.assistant, str)

    # Loading state should have version 1 now
    state = await store.load(conv_id)
    assert state.version == 1

    # Simulate stale append (expected_version=0) -> OCC conflict
    with pytest.raises(RuntimeError):
        await store.append(
            conv_id, expected_version=0, ex=Exchange("stale", "", error=False)
        )
