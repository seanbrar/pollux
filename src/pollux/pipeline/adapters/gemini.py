"""Gemini provider adapter: small surface for generation/uploads/cache.

This file hosts the concrete adapter used by the API handler when the real
API path is enabled. It deliberately exposes only the minimal methods needed
by the handler.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from pollux.pipeline.adapters.base import BaseProviderAdapter, GenerationAdapter
from pollux.pipeline.adapters.registry import register_adapter

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from concurrent.futures import Executor

    from pollux.config import FrozenConfig
    from pollux.pipeline.execution_state import ExecutionHints

log = logging.getLogger(__name__)


class GoogleGenAIAdapter(GenerationAdapter):
    """Tiny adapter that translates neutral types to Google provider calls."""

    def __init__(
        self,
        api_key: str,
        *,
        executor: Executor | None = None,
        clock: Callable[[], float] | None = None,
    ):
        """Initialize the Google client with the provided API key.

        Optional executor and clock allow deterministic testing and custom execution
        control without complicating the default path.
        """
        try:
            import google.genai as genai
        except Exception as e:  # pragma: no cover - environment dependent
            raise RuntimeError("google-genai SDK is not installed") from e
        self._client = genai.Client(api_key=api_key)
        self._types = genai.types
        self._hints: ExecutionHints | None = None
        # Optional execution controls
        self._executor: Executor | None = executor
        self._clock: Callable[[], float] | None = clock

    def apply_hints(self, hints: ExecutionHints) -> None:
        """Accept execution hints for potential provider configuration."""
        self._hints = hints

    async def upload_file_local(
        self,
        path: os.PathLike[str] | str,
        mime_type: str | None,
    ) -> Any:
        """Upload a file using the provider SDK and return a neutral handle.

        Returns a library-owned `FileRefPart` (preferred) or a minimal mapping
        with a `uri` key so the API handler can substitute it reliably.
        """
        loop = asyncio.get_running_loop()

        def _upload() -> Any:
            return self._client.files.upload(file=os.fspath(path))

        uploaded = await loop.run_in_executor(self._executor, _upload)

        # Normalize provider file object into neutral FileRefPart when possible
        try:
            from pollux.core.types import (
                FileRefPart,  # local import to avoid cycles
            )

            # Prefer SDK "uri" attribute for full URI, fall back to "name" for short format
            # The full URI is more reliable for content generation
            uri_attr = getattr(uploaded, "uri", None)
            if isinstance(uri_attr, str) and uri_attr.strip():
                return FileRefPart(
                    uri=uri_attr, mime_type=mime_type, raw_provider_data=uploaded
                )
            # Fallback to name attribute (short format)
            name_attr = getattr(uploaded, "name", None)
            if isinstance(name_attr, str) and name_attr.strip():
                return FileRefPart(
                    uri=name_attr, mime_type=mime_type, raw_provider_data=uploaded
                )
            # Dict-like response variants
            if isinstance(uploaded, dict):
                # Prefer full URI over short name format
                if isinstance(uploaded.get("uri"), str):
                    return FileRefPart(
                        uri=uploaded["uri"],
                        mime_type=mime_type,
                        raw_provider_data=uploaded,
                    )
                if isinstance(uploaded.get("name"), str):
                    return FileRefPart(
                        uri=uploaded["name"],
                        mime_type=mime_type,
                        raw_provider_data=uploaded,
                    )
        except Exception:  # pragma: no cover - never fail upload due to normalization
            log.debug(
                "upload normalization failed; returning raw object", exc_info=True
            )

        # Fallback: return a minimal mapping the handler can coerce later
        # Attempt to surface some identifier as `uri`
        candidate = getattr(uploaded, "name", None) or getattr(uploaded, "uri", None)
        if isinstance(candidate, str) and candidate.strip():
            return {"uri": candidate, "mime_type": mime_type}
        return uploaded

    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],
        system_instruction: str | None,
        ttl_seconds: int | None,
    ) -> str:
        """Create a cached content object and return its provider name."""
        parts = [self._to_provider_part(p) for p in content_parts]

        def _create() -> Any:
            cfg = self._types.CreateCachedContentConfig(
                contents=parts,
                system_instruction=system_instruction,
            )
            if ttl_seconds is not None:
                from contextlib import suppress

                with suppress(Exception):
                    cfg.ttl = f"{int(ttl_seconds)}s"
            return self._client.caches.create(model=model_name, config=cfg)

        loop = asyncio.get_running_loop()
        cache = await loop.run_in_executor(self._executor, _create)
        name = getattr(cache, "name", None)
        if isinstance(name, str):
            return name
        return f"cachedContents/{abs(hash((model_name, len(parts)))) % (1 << 32)}"

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:
        """Generate content using the provider SDK and normalize the response."""
        parts = [self._to_provider_part(p) for p in api_parts]
        config = self._to_provider_config(api_config)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            self._executor,
            lambda: self._client.models.generate_content(
                model=model_name, contents=parts, config=config
            ),
        )
        return self._to_minimal_raw_dict(response, model_name)

    # --- Provider conversions ---
    def _to_provider_part(self, part: Any) -> Any:
        """Coerce a neutral part to a provider SDK part.

        The SDK's shape can vary across versions; we defensively fall back to a
        minimal dict when constructing provider types fails.
        """
        # Structured conversation history: render turns deterministically to text
        # HistoryPart is validated by core types; render deterministically.
        from pollux.core.types import HistoryPart

        if isinstance(part, HistoryPart):

            def _render_history(turns: tuple[Any, ...]) -> str:
                # HistoryPart.turns is tuple[Turn, ...]; question/answer are str
                if not turns:
                    return ""
                lines: list[str] = []
                for t in turns:
                    lines.append(f"User: {t.question}")
                    lines.append(f"Assistant: {t.answer}")
                return "\n".join(lines)

            rendered = _render_history(part.turns)
            try:
                return self._types.Part(text=rendered)
            except Exception:  # pragma: no cover - SDK shape differences
                return {"text": rendered}
        # Neutral text
        if hasattr(part, "text"):
            text_attr = cast("Any", part).text
            try:
                return self._types.Part(text=text_attr)
            except Exception:  # pragma: no cover - SDK shape differences
                return {"text": str(text_attr)}
        # Neutral file reference
        try:
            from pollux.core.types import (  # local to avoid cycles
                FileInlinePart,
                FileRefPart,
            )

            if isinstance(part, FileRefPart):
                # Prefer SDK type; fall back to a simple dict with well-known key
                try:
                    # Different SDK versions may use file_data or other fields
                    return self._types.Part(
                        file_data=self._types.FileData(file_uri=part.uri)
                    )
                except Exception:  # pragma: no cover - SDK variability
                    return {"file_uri": part.uri, "mime_type": part.mime_type}
            if isinstance(part, FileInlinePart):
                try:
                    return self._types.Part(
                        inline_data=self._types.Blob(
                            mime_type=part.mime_type, data=bytes(part.data)
                        )
                    )
                except Exception:  # pragma: no cover
                    return {"inline_data": True, "mime_type": part.mime_type}
        except Exception:  # pragma: no cover - type import issues shouldn't break
            log.exception("Failed to convert part")
        return part

    def _to_provider_config(self, api_config: dict[str, object]) -> Any:
        """Convert neutral config dict into a provider config object."""
        try:
            cfg = self._types.GenerateContentConfig()
            for key, value in api_config.items():
                from contextlib import suppress

                with suppress(Exception):
                    setattr(cfg, key, value)
            # Tighten: never silently drop critical keys like cached_content.
            # If the typed config cannot carry it, fall back to dict config.
            if "cached_content" in api_config:
                try:
                    if not hasattr(cfg, "cached_content"):
                        return api_config
                    applied = getattr(cfg, "cached_content", None)
                    expected = api_config.get("cached_content")
                    # If a non-empty cached_content was requested but not applied, use dict
                    if expected not in (None, "", False) and applied in (
                        None,
                        "",
                        False,
                    ):
                        return api_config
                except Exception:  # pragma: no cover - be robust to SDK shape issues
                    return api_config
            return cfg
        except Exception:  # pragma: no cover
            return api_config

    def _to_minimal_raw_dict(self, response: Any, model_name: str) -> dict[str, Any]:
        """Normalize provider response to a minimal serializable dict."""
        if hasattr(response, "text") and isinstance(response.text, str):
            usage = self._extract_usage(response)
            return {"text": response.text, "model": model_name, "usage": usage}

        first_text = None
        try:
            if getattr(response, "candidates", None):
                cand0 = response.candidates[0]
                content = getattr(cand0, "content", None)
                parts = getattr(content, "parts", None)
                if parts and len(parts) > 0 and hasattr(parts[0], "text"):
                    first_text = parts[0].text
        except Exception:
            first_text = None

        return {
            "model": model_name,
            "candidates": [{"content": {"parts": [{"text": first_text or ""}]}}],
            "usage": self._extract_usage(response),
        }

    def _extract_usage(self, response: Any) -> dict[str, int]:
        """Extract usage counters from the provider response if present."""
        usage = {
            "prompt_token_count": 0,
            "source_token_count": 0,
            "total_token_count": 0,
        }
        try:
            meta = getattr(response, "usage_metadata", None)
            if meta is not None:
                pt = int(getattr(meta, "prompt_token_count", 0) or 0)
                ot = int(getattr(meta, "candidates_token_count", 0) or 0)
                tt = int(getattr(meta, "total_token_count", pt + ot) or (pt + ot))
                # Optional cached content counter when provided by SDK
                cc = int(getattr(meta, "cached_content_token_count", 0) or 0)
                usage.update(
                    {
                        "prompt_token_count": pt,
                        "source_token_count": max(tt - pt, 0),
                        "total_token_count": tt,
                        "cached_content_token_count": cc,
                    }
                )
        except Exception:
            log.exception("Failed to extract usage metadata")
        return usage


# --- Provider Configuration Adapter ---


class GeminiProviderAdapter(BaseProviderAdapter):
    """Gemini-specific provider adapter for configuration customization.

    This adapter transforms generic FrozenConfig into Gemini-specific
    configuration shapes, following the adapter seam pattern.
    """

    name = "google"

    def build_provider_config(self, cfg: FrozenConfig) -> Mapping[str, Any]:
        """Build Gemini-specific configuration from FrozenConfig.

        Adds Gemini-specific fields and transformations while preserving
        the core configuration values.

        Args:
            cfg: The resolved, immutable configuration.

        Returns:
            Gemini-optimized configuration mapping.
        """
        config = {
            "model": cfg.model,
            "api_key": cfg.api_key,
            "use_real_api": cfg.use_real_api,
            "enable_caching": cfg.enable_caching,
            "ttl_seconds": cfg.ttl_seconds,
            "telemetry_enabled": cfg.telemetry_enabled,
            "tier": cfg.tier,
        }

        # Add Gemini-specific configuration from extras if present
        if "timeout_s" in cfg.extra:
            config["timeout_s"] = cfg.extra["timeout_s"]
        if "base_url" in cfg.extra:
            config["base_url"] = cfg.extra["base_url"]

        return config


# Register the Gemini adapter on module import
register_adapter(GeminiProviderAdapter())
