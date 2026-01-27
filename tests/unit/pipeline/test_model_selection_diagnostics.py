from __future__ import annotations

import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand
from pollux.executor import create_executor


@pytest.mark.asyncio
async def test_model_selection_diagnostics_present_for_mock_pipeline():
    cfg = resolve_config()
    ex = create_executor(cfg)
    cmd = InitialCommand.strict(
        sources=(), prompts=("Where is 00:10 discussed?",), config=cfg
    )
    result = await ex.execute(cmd)
    # Diagnostics should include model_selected (best-effort advisory)
    diag = result.get("diagnostics") or {}
    assert isinstance(diag, dict)
    assert "model_selected" in diag
    sel = diag.get("model_selected")
    assert isinstance(sel, dict)
    assert "selected" in sel
