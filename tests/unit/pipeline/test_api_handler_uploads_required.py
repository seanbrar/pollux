import os
from typing import Any

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
    UploadTask,
)
from pollux.pipeline.api_handler import APIHandler


class _NoUploadAdapter:
    async def generate(
        self,
        *,
        model_name: str,  # noqa: ARG002
        api_parts: tuple[Any, ...],  # noqa: ARG002
        api_config: dict[str, object],  # noqa: ARG002
    ) -> dict[str, Any]:
        return {
            "text": "ok",
            "model": "gemini-2.0-flash",
            "usage": {"total_token_count": 1},
        }


class _UploadCapableAdapter(_NoUploadAdapter):
    async def upload_file_local(
        self,
        path: os.PathLike[str] | str,
        mime_type: str | None,  # noqa: ARG002
    ) -> Any:
        return {"uri": f"files/mock/{os.fspath(path)}"}


@pytest.mark.skip(
    reason="ExecutionPlan.upload_tasks no longer enforced; use placeholders if needed"
)
async def test_required_uploads_fail_when_provider_cannot_upload(tmp_path): ...


@pytest.mark.asyncio
async def test_optional_uploads_skip_when_provider_cannot_upload(tmp_path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "k"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name="gemini-2.0-flash", api_parts=(TextPart("p"),), api_config={}
    )
    plan = ExecutionPlan(
        calls=(call,),
        upload_tasks=(
            UploadTask(part_index=0, local_path=tmp_path / "f.txt", required=False),
        ),
    )
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    handler = APIHandler(adapter=_NoUploadAdapter())
    result = await handler.handle(planned)
    assert isinstance(result, Success)


@pytest.mark.skip(
    reason="ExecutionPlan.upload_tasks no longer enforced; use placeholders if needed"
)
async def test_required_uploads_succeed_when_provider_can_upload(tmp_path): ...
