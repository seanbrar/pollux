from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_store import JSONStore
from pollux.extensions.conversation_types import Exchange

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.core.types import InitialCommand, ResultEnvelope

pytestmark = pytest.mark.unit


class _StubConfig:
    def to_frozen(self) -> Any:
        return self


class _StubExecutor:
    def __init__(self) -> None:
        self.config = _StubConfig()

    async def execute(self, _command: InitialCommand) -> ResultEnvelope:
        prompts = tuple(getattr(_command, "prompts", ()) or ())
        return {
            "status": "ok",
            "answers": [f"ok: {p}" for p in prompts],
            "extraction_method": "stub",
            "confidence": 1.0,
            "usage": {"total_tokens": 10},
            "metrics": {"token_validation": {"estimated_max": 20, "actual": 10}},
        }


@pytest.mark.asyncio
async def test_json_store_occ_and_engine(tmp_path: Path) -> None:
    store_path = tmp_path / "store.json"
    store = JSONStore(str(store_path))
    engine = ConversationEngine(_StubExecutor(), store)

    conv_id = "demo-1"
    # First turn via engine
    ex = await engine.ask(conv_id, "Hello?")
    assert isinstance(ex.assistant, str)

    # Version increases
    state = await store.load(conv_id)
    assert state.version == 1

    # OCC conflict on stale append
    with pytest.raises(RuntimeError):
        await store.append(
            conv_id, expected_version=0, ex=Exchange("u", "a", error=False)
        )
