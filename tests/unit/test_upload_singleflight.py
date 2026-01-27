from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from pollux.core.api_plan import UploadTask
from pollux.core.types import APIPart, FilePlaceholder
from pollux.pipeline.adapters.base import UploadsCapability
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.registries import FileRegistry


@dataclass
class _FakeUploadsAdapter(UploadsCapability):
    calls: int = 0

    async def upload_file_local(
        self, path: str | os.PathLike[str], mime_type: str | None
    ) -> Any:
        self.calls += 1
        await asyncio.sleep(0.05)
        return {"uri": f"mock://{os.fspath(path)}", "mime_type": mime_type}


@pytest.mark.asyncio
async def test_upload_single_flight_for_same_file() -> None:
    # Prepare two UploadTasks referencing the same file id
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "doc.txt"
        p.write_text("hello")
        t1 = UploadTask(
            part_index=0, local_path=p, mime_type="text/plain", required=False
        )
        t2 = UploadTask(
            part_index=1, local_path=p, mime_type="text/plain", required=False
        )

        handler = APIHandler(registries={"files": FileRegistry()})
        adapter = _FakeUploadsAdapter()

        # Call the internal helper directly to isolate behavior
        # Provide parts corresponding to indices for cleanup inspection
        parts: list[APIPart] = [
            FilePlaceholder(local_path=p, mime_type="text/plain", ephemeral=False),
            FilePlaceholder(local_path=p, mime_type="text/plain", ephemeral=False),
        ]
        res = await handler._upload_pending(adapter, [(0, t1), (1, t2)], parts)
        # Should have two results, one upload
        assert len(res) == 2
        assert adapter.calls == 1
        # Both entries should have the same uploaded URI
        uris = {
            uploaded.get("uri") for _, uploaded in res if isinstance(uploaded, dict)
        }
        assert len(uris) == 1
