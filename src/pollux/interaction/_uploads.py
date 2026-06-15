"""Core-orchestrated file upload and cleanup for the v2 execution path.

These helpers let core resolve an environment's local-file source parts into
provider assets once (single-flight deduped) before fanning out, and clean them
up afterward. Uploads and deletes are optional provider capabilities, so the
helpers narrow on the :class:`FileUploadingProvider` / :class:`FileDeletingProvider`
structural protocols.
"""

from __future__ import annotations

import asyncio  # noqa: TC003
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.errors import APIError, InternalError, PolluxError
from pollux.providers.base import FileDeletingProvider
from pollux.providers.models import ProviderFileAsset, is_file_part
from pollux.retry import retry_async, should_retry_side_effect

if TYPE_CHECKING:
    from pollux.providers.base import FileUploadingProvider, Provider
    from pollux.retry import RetryPolicy

logger = logging.getLogger(__name__)


def _with_call_idx(err: APIError, call_idx: int | None) -> APIError:
    """Return an APIError attributed to *call_idx* without mutating in place.

    A shared single-flight failure (e.g. one file upload feeding many calls)
    can be observed by several concurrent waiters, so re-raise a copy rather
    than stamping the shared instance.
    """
    if call_idx is None or err.call_idx is not None:
        return err

    message = err.args[0] if err.args else str(err)
    cls: type[APIError] = type(err)
    return cls(
        message,
        hint=err.hint,
        retryable=err.retryable,
        status_code=err.status_code,
        retry_after_s=err.retry_after_s,
        provider=err.provider,
        phase=err.phase,
        call_idx=call_idx,
        error_category=err.error_category,
    )


async def substitute_upload_parts(
    parts: list[Any],
    *,
    provider: FileUploadingProvider,
    call_idx: int | None,
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
    upload_inflight: dict[tuple[str, str], asyncio.Future[ProviderFileAsset]],
    upload_lock: asyncio.Lock,
    retry_policy: RetryPolicy,
) -> list[Any]:
    """Replace local file placeholders with provider file assets."""
    resolved: list[Any] = []

    for part in parts:
        if is_file_part(part):
            file_path = part["file_path"]
            mime_type = part["mime_type"]
            provider_hints = part.get("provider_hints")
            cache_key = (file_path, mime_type)

            async def _work(
                fp: str = file_path, mt: str = mime_type
            ) -> ProviderFileAsset:
                try:
                    if retry_policy.max_attempts <= 1:
                        return await provider.upload_file(Path(fp), mt)

                    return await retry_async(
                        lambda: provider.upload_file(Path(fp), mt),
                        policy=retry_policy,
                        should_retry=should_retry_side_effect,
                    )
                except PolluxError:
                    raise
                except Exception as e:
                    raise InternalError(
                        f"Upload failed: {type(e).__name__}: {e}",
                        hint="This is a Pollux internal error. Please report it.",
                    ) from e

            try:
                asset = await singleflight_cached(
                    cache_key,
                    lock=upload_lock,
                    inflight=upload_inflight,
                    cache_get=upload_cache.get,
                    cache_set=upload_cache.__setitem__,
                    work=_work,
                )
            except APIError as e:
                raise _with_call_idx(e, call_idx) from e

            # The provider adapter reconstructs the SDK payload from the asset.
            if provider_hints is not None:
                resolved.append(
                    {
                        "uri": asset.file_id,
                        "mime_type": mime_type,
                        "provider_hints": provider_hints,
                    }
                )
            else:
                resolved.append(asset)
            continue

        resolved.append(part)

    return resolved


async def cleanup_uploads(
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
    provider: Provider,
) -> None:
    """Delete provider-managed uploaded files (best-effort).

    Only applies to providers exposing ``delete_file`` (currently OpenAI).
    Failures are logged, never raised—the server-side TTL is the backstop.
    """
    if not isinstance(provider, FileDeletingProvider):
        return

    file_ids = [
        asset.file_id
        for asset in upload_cache.values()
        if asset.provider == "openai" and not asset.is_inline_fallback
    ]

    for file_id in file_ids:
        try:
            await provider.delete_file(file_id)
            logger.debug("Deleted uploaded file: %s", file_id)
        except Exception as exc:
            logger.debug("Failed to delete uploaded file %s: %s", file_id, exc)
