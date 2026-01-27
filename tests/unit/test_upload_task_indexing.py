from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, TypedDict

import pytest

from pollux.core.api_plan import UploadTask
from pollux.core.types import APIPart, FilePlaceholder, TextPart
from pollux.pipeline.adapters.base import UploadsCapability
from pollux.pipeline.api_handler import APIHandler

if TYPE_CHECKING:
    from os import PathLike


class _UploadRef(TypedDict):
    uri: str
    mime_type: str | None


@dataclass
class _FakeUploadsAdapter(UploadsCapability):
    calls: int = 0

    async def upload_file_local(
        self, path: str | PathLike[str], mime_type: str | None
    ) -> _UploadRef:
        self.calls += 1
        await asyncio.sleep(0.01)
        return {"uri": f"mock://{Path(path)}", "mime_type": mime_type}


@pytest.mark.asyncio
async def test_upload_task_indices_are_relative_to_call_parts() -> None:
    # Arrange: one shared part, then per-call parts where index 1 is the file
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "doc.txt"
        p.write_text("hello")

        shared: list[APIPart] = [TextPart("shared")]  # length = 1
        call_parts: list[APIPart] = [
            TextPart("prompt"),
            FilePlaceholder(local_path=p, mime_type="text/plain", ephemeral=False),
        ]
        combined = list(shared) + list(call_parts)

        # UploadTask index 1 refers to the second element in per-call parts,
        # which should map to combined index 1 + len(shared) == 2
        tasks = (
            UploadTask(
                part_index=1, local_path=p, mime_type="text/plain", required=True
            ),
        )

        handler = APIHandler()
        adapter = _FakeUploadsAdapter()
        out = await handler._prepare_effective_parts(
            adapter,
            combined,
            upload_tasks=tasks,
            infer_placeholders=False,
            call_offset=len(shared),
        )

        # Assert: combined index 2 replaced by uploaded ref (coerced to FileRefPart)
        from pollux.core.types import FileRefPart

        assert isinstance(out[2], FileRefPart)
        assert adapter.calls == 1
