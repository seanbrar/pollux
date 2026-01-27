"""Remote file materialization stage (core, provider-neutral).

Converts eligible HTTP(S) file references (e.g., PDFs, arXiv) into local
file placeholders prior to upload handling. This keeps the API handler
focused on upload substitution while making remote materialization explicit
and controllable via `ExecutionOptions.remote_files`.

Current behavior: feature is opt-in (disabled by default). When enabled,
the stage can scan shared parts only or both shared and per-call parts
according to policy. It supports bounded concurrency, single-flight by URI,
and conservative content-type/size checks. HTTPS is required by default.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pollux.core.exceptions import APIError
from pollux.core.execution_options import RemoteFilePolicy
from pollux.core.types import (
    APICall,
    Failure,
    FilePlaceholder,
    FileRefPart,
    PlannedCommand,
    Result,
    Success,
)
from pollux.pipeline.base import BaseAsyncHandler
from pollux.telemetry import TelemetryContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pollux.core.api_plan import ExecutionPlan


class RemoteMaterializationStage(
    BaseAsyncHandler[PlannedCommand, PlannedCommand, APIError]
):
    """Materialize eligible remote file refs into local placeholders.

    Current behavior:
      - No-op unless `ExecutionOptions.remote_files.enabled` is True.
      - Scope is controlled by policy: shared-only or shared+per-call.
      - Detects HTTPS (or HTTP when explicitly allowed) PDFs via MIME or
        `.pdf` extension or arXiv `abs/` URI.
      - Downloads and replaces with `FilePlaceholder(ephemeral=True)` at the
        same index.

    Notes:
      - This stage already supports bounded concurrency, single-flight
        deduplication by URI, per-call scanning (policy-controlled), and basic
        telemetry. Behavior is intentionally conservative and opt-in.
    """

    def __init__(self) -> None:
        """Initialize the stage with a safe no-op telemetry context."""
        # Safe no-op unless enabled via reporters/env
        self._telemetry = TelemetryContext()

    async def handle(self, command: PlannedCommand) -> Result[PlannedCommand, APIError]:
        """Materialize eligible HTTP(S) file refs into local placeholders.

        No-op unless enabled via `ExecutionOptions.remote_files`. Applies to both
        shared and per-call parts with bounded concurrency and single-flight by URI.
        """
        try:
            policy = _get_policy(command)
            if policy is None or not policy.enabled:
                return Success(command)

            plan = command.execution_plan

            # Gather targets across shared and per-call parts according to scope
            shared_targets = _scan_parts(tuple(plan.shared_parts), policy)
            call_targets: list[tuple[int, int, str, str | None]] = []
            if getattr(policy, "scope", "shared_and_calls") == "shared_and_calls":
                for ci, c in enumerate(plan.calls):
                    tgs = _scan_parts(tuple(c.api_parts), policy)
                    call_targets.extend((ci, pi, u, m) for (pi, u, m) in tgs)

            if not shared_targets and not call_targets:
                return Success(command)

            # Download with bounded concurrency and single-flight by URI
            from time import perf_counter

            t0 = perf_counter()
            downloads, stats = await _download_uris(
                [u for (_, u, _) in shared_targets]
                + [u for (_, _, u, _) in call_targets],
                policy,
            )
            duration = max(perf_counter() - t0, 0.0)

            # Apply replacements to shared parts
            new_shared = list(plan.shared_parts)
            promoted_shared = 0
            skipped_shared = 0
            for idx, uri, _mime in shared_targets:
                info = downloads.get(uri)
                if info is None or info.get("path") is None:
                    skipped_shared += 1
                    continue
                promoted_shared += 1
                path = info["path"]
                new_shared[idx] = FilePlaceholder(
                    local_path=Path(str(path)),
                    mime_type=getattr(plan.shared_parts[idx], "mime_type", None),
                    ephemeral=True,
                )

            # Apply replacements to per-call parts
            new_calls: list[APICall] = []
            promoted_calls = 0
            skipped_calls = 0
            # Build per-call target mapping for faster lookups
            per_call_map: dict[int, list[tuple[int, str]]] = {}
            for ci, pi, uri, _m in call_targets:
                per_call_map.setdefault(ci, []).append((pi, uri))
            for ci, call in enumerate(plan.calls):
                if ci not in per_call_map:
                    new_calls.append(call)
                    continue
                parts = list(call.api_parts)
                for pi, uri in per_call_map[ci]:
                    info = downloads.get(uri)
                    if info is None or info.get("path") is None:
                        skipped_calls += 1
                        continue
                    promoted_calls += 1
                    path = info["path"]
                    parts[pi] = FilePlaceholder(
                        local_path=Path(str(path)),
                        mime_type=getattr(call.api_parts[pi], "mime_type", None),
                        ephemeral=True,
                    )
                new_calls.append(replace(call, api_parts=tuple(parts)))

            new_plan: ExecutionPlan = replace(
                plan, shared_parts=tuple(new_shared), calls=tuple(new_calls)
            )
            updated = replace(command, execution_plan=new_plan)

            # Minimal telemetry for observability
            with self._telemetry("remote.materialize") as tele:
                tele.gauge(
                    "promoted_count",
                    float(stats.get("promoted", 0) + promoted_shared + promoted_calls),
                )
                tele.gauge("bytes_total", float(stats.get("bytes", 0)))
                tele.gauge(
                    "skipped",
                    float(stats.get("skipped", 0) + skipped_shared + skipped_calls),
                )
                tele.gauge("errors", float(stats.get("errors", 0)))
                tele.gauge("duration_s", float(duration))
                tele.gauge("uris_total", float(stats.get("uris_total", 0)))
                tele.gauge("uris_unique", float(stats.get("uris_unique", 0)))
                tele.gauge("dedup_savings", float(stats.get("dedup_savings", 0)))
                tele.gauge(
                    "download_concurrency",
                    float(max(1, int(policy.download_concurrency))),
                )
            return Success(updated)
        except asyncio.CancelledError:
            # Preserve cooperative cancellation semantics
            raise
        except APIError as e:
            return Failure(e)
        except Exception as e:  # pragma: no cover - defensive normalization
            return Failure(APIError(f"Remote materialization failed: {e}"))


def _get_policy(command: PlannedCommand) -> RemoteFilePolicy | None:
    try:
        opts = getattr(command.resolved.initial, "options", None)
        if opts is None:
            return None
        pol = getattr(opts, "remote_files", None)
        return pol if isinstance(pol, RemoteFilePolicy) else None
    except Exception:
        return None


def _scan_parts(
    parts: tuple[Any, ...], policy: RemoteFilePolicy
) -> list[tuple[int, str, str | None]]:
    """Return indices and canonical URIs for parts eligible for promotion.

    Each item is (part_index, canonical_uri, mime_type).
    Canonicalization includes arXiv abs->pdf mapping.
    """
    targets: list[tuple[int, str, str | None]] = []
    for idx, p in enumerate(parts):
        if isinstance(p, FileRefPart):
            uri = str(getattr(p, "uri", "") or "")
            mt = getattr(p, "mime_type", None)
            if _is_http_pdf(uri, mt, policy):
                targets.append((idx, _canonicalize_arxiv(uri), mt))
    return targets


async def _download_uris(
    uris: list[str], policy: RemoteFilePolicy
) -> tuple[dict[str, dict[str, int | str | None]], dict[str, int]]:
    # Concurrency with bounded semaphore; URIs are deduplicated prior to scheduling
    sem = asyncio.Semaphore(max(1, int(policy.download_concurrency)))
    downloads: dict[str, dict[str, int | str | None]] = {}
    errors = 0

    async def _one(uri: str) -> None:
        nonlocal errors
        try:
            async with sem:
                path, nbytes = await _download_to_temp(uri, policy)
                downloads[uri] = {"path": path, "bytes": nbytes}
        except asyncio.CancelledError:
            # Propagate cancellation without counting as an error
            raise
        except Exception:
            if policy.on_error == "skip":
                log.debug(
                    "remote materialization skipped due to error for URI: %s",
                    uri,
                    exc_info=True,
                )
                downloads[uri] = {"path": None, "bytes": 0}
            else:
                errors += 1
                raise

    unique = []
    seen: set[str] = set()
    for u in uris:
        if u not in seen:
            unique.append(u)
            seen.add(u)

    # Use named tasks + robust cancellation/drain
    tasks = [
        asyncio.create_task(_one(u), name=f"remote_materialization:{u}") for u in unique
    ]
    try:
        await asyncio.gather(*tasks, return_exceptions=False)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    except Exception:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    total_bytes = 0
    skipped = 0
    promoted = 0
    for info in downloads.values():
        if info.get("path") is None:
            skipped += 1
        else:
            promoted += 1
            with contextlib.suppress(Exception):
                total_bytes += int(info.get("bytes", 0) or 0)
    stats = {
        "promoted": promoted,
        "bytes": total_bytes,
        "skipped": skipped,
        "errors": errors,
        "uris_total": len(uris),
        "uris_unique": len(unique),
        "dedup_savings": max(0, len(uris) - len(unique)),
    }
    return downloads, stats


def _is_http_pdf(uri: str, mime: str | None, policy: RemoteFilePolicy) -> bool:
    u = uri.strip().lower()
    if not (u.startswith(("http://", "https://"))):
        return False
    if u.startswith("http://") and not getattr(policy, "allow_http", False):
        return False
    if mime and mime.lower() in policy.allowed_mime_types:
        return True
    if policy.allow_pdf_extension_heuristic and u.endswith(".pdf"):
        return True
    # arXiv `abs/` links imply a PDF at a derived URL
    return "arxiv.org/abs/" in u


def _canonicalize_arxiv(uri: str) -> str:
    u = uri.strip()
    low = u.lower()
    if "arxiv.org/abs/" in low:
        # Preserve id/version after abs/
        after = u.split("/abs/", 1)[1]
        # Drop any fragment; keep query/version suffix as-is
        base = after.split("#", 1)[0]
        return f"https://arxiv.org/pdf/{base}.pdf"
    return u


async def _download_to_temp(uri: str, policy: RemoteFilePolicy) -> tuple[str, int]:
    """Download URI to a temporary file with basic safety limits.

    Minimal implementation: sequential download with size cap and timeouts.
    """
    import asyncio
    import os
    import tempfile
    from urllib.request import Request, urlopen

    def _do() -> tuple[str, int]:
        # Defensive guard: only allow http(s) schemes; other schemes are unexpected.
        low = uri.lower()
        if not low.startswith(("http://", "https://")):
            raise APIError(f"Unsupported URI scheme for materialization: {uri}")
        if low.startswith("http://") and not getattr(policy, "allow_http", False):
            raise APIError(f"HTTP not allowed by policy for URI: {uri}")

        req = Request(  # noqa: S310 - http(s) only, validated above
            uri, headers={"User-Agent": "gemini-batch/remote-materializer"}
        )
        # urllib uses a single timeout parameter; apply the maximum of the
        # configured connect/read timeouts to approximate the stricter bound.
        timeout = max(
            max(float(policy.connect_timeout_s), 0.0),
            max(float(policy.read_timeout_s), 0.0),
            0.1,
        )

        # Open the URL first to inspect Content-Type and decide suffix
        tmp_fd: int | None = None
        path: str | None = None
        total = 0
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - controlled source
                # Validate final URL scheme after redirects
                try:
                    final_url = str(getattr(resp, "geturl", lambda: uri)())
                except Exception:
                    final_url = uri
                low_final = final_url.lower()
                if not low_final.startswith(("http://", "https://")):
                    raise APIError(
                        f"Unexpected final URL scheme after redirect: {final_url}"
                    )
                if low_final.startswith("http://") and not getattr(
                    policy, "allow_http", False
                ):
                    raise APIError(f"HTTP not allowed by policy for URI: {final_url}")
                ctype = str(resp.headers.get("Content-Type", "")).lower()
                if ctype and not any(
                    ctype.startswith(mt) for mt in policy.allowed_mime_types
                ):
                    raise APIError(f"Unexpected Content-Type: {ctype}")

                # Decide suffix based on Content-Type or URL path
                suffix = ".pdf"
                if ctype:
                    if "pdf" not in ctype and policy.allowed_mime_types:
                        # Pick a conservative generic extension
                        suffix = ".bin"
                else:
                    from urllib.parse import urlparse

                    parsed = urlparse(uri)
                    suffix = ".pdf" if parsed.path.lower().endswith(".pdf") else ".bin"

                tmp_fd, path = tempfile.mkstemp(suffix=suffix)
                need_magic_pdf_check = not ctype and suffix == ".pdf"
                while True:
                    chunk: bytes = resp.read(64 * 1024)
                    if not chunk:
                        break
                    if need_magic_pdf_check:
                        # Lightweight validation for PDFs when MIME is absent and we used extension heuristic
                        head = chunk.lstrip()[:5]
                        if not head.startswith(b"%PDF"):
                            raise APIError(
                                "Unexpected file signature for .pdf URL (missing %PDF header)"
                            )
                        need_magic_pdf_check = False
                    total += len(chunk)
                    if policy.max_bytes and total > policy.max_bytes:
                        raise APIError(
                            f"Remote file exceeds size limit ({total} > {policy.max_bytes})"
                        )
                    os.write(tmp_fd, chunk)
        except Exception:
            # Best-effort unlink on any failure after a path was created
            if path:
                with contextlib.suppress(Exception):
                    os.close(tmp_fd)  # type: ignore[arg-type]
                with contextlib.suppress(Exception):
                    Path(path).unlink()
                # Avoid double-close in finally
                tmp_fd = None
            raise
        finally:
            if tmp_fd is not None:
                with contextlib.suppress(Exception):
                    os.close(tmp_fd)
        if path is None:
            raise APIError("Failed to materialize remote file: no path created")
        return path, total

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do)
