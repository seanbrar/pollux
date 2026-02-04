"""Gemini provider implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pollux.errors import APIError
from pollux.providers.base import ProviderCapabilities

if TYPE_CHECKING:
    from pathlib import Path


class GeminiProvider:
    """Google Gemini API provider."""

    def __init__(self, api_key: str) -> None:
        """Create provider with an API key."""
        self.api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            try:
                from google import genai
            except ImportError as e:
                raise APIError(
                    "google-genai package not installed",
                    hint="uv pip install google-genai",
                ) from e

            # Initialize with just API key as per 'Gemini Developer API' instructions.
            # If user wanted Vertex, they'd need to provide project/location logic,
            # but current impl only took api_key.
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports context caching."""
        return self.capabilities.caching

    @property
    def supports_uploads(self) -> bool:
        """Whether this provider supports file uploads."""
        return self.capabilities.uploads

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            caching=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
        )

    def _convert_parts(self, parts: list[Any]) -> list[Any]:
        """Convert internal part representation to google-genai SDK types."""
        from google.genai import types

        converted: list[Any] = []
        for p in parts:
            if isinstance(p, str):
                converted.append(p)
            elif isinstance(p, dict):
                # Handle URI-based parts (after upload)
                if "uri" in p and "mime_type" in p:
                    converted.append(
                        types.Part(
                            file_data=types.FileData(
                                file_uri=p["uri"], mime_type=p["mime_type"]
                            )
                        )
                    )
                # Handle text parts in dict
                elif "text" in p:
                    converted.append(p["text"])
                else:
                    # Fallback for other dicts, though we should likely validate
                    converted.append(p)
            else:
                converted.append(p)
        return converted

    async def generate(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        cache_name: str | None = None,
        response_schema: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        history: list[dict[str, str]] | None = None,
        delivery_mode: str = "realtime",
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate content using Gemini API."""
        _ = (
            response_schema,
            reasoning_effort,
            history,
            delivery_mode,
            previous_response_id,
        )
        client = self._get_client()
        config: dict[str, Any] = {}
        if system_instruction is not None:
            config["system_instruction"] = system_instruction
        if cache_name is not None:
            config["cached_content"] = cache_name
        if response_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = response_schema

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=self._convert_parts(parts),
                config=config or None,
            )
            return self._parse_response(response)
        except Exception as e:
            raise APIError(f"Gemini generate failed: {e}") from e

    async def upload_file(self, path: Path, mime_type: str) -> str:
        """Upload a file to Gemini."""
        client = self._get_client()

        try:
            # New SDK uses client.files.upload (or client.aio.files.upload)
            result = await client.aio.files.upload(
                file=path, config={"mime_type": mime_type}
            )
            return str(result.uri)
        except Exception as e:
            raise APIError(f"Gemini upload failed: {e}") from e

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a cached content entry."""
        client = self._get_client()
        from google.genai import types

        try:
            result = await client.aio.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    contents=self._convert_parts(parts),
                    system_instruction=system_instruction,
                    ttl=f"{ttl_seconds}s",
                ),
            )
            return str(result.name)
        except Exception as e:
            raise APIError(f"Gemini cache creation failed: {e}") from e

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Parse Gemini response into a standard dict."""
        text = ""
        structured: Any = None
        try:
            if hasattr(response, "text"):
                text = response.text or ""
            # Fallbacks similar to before, but new SDK usually gives .text
            # if candidates exist and have text.
        except Exception:
            text = ""
        try:
            structured = getattr(response, "parsed", None)
            if structured is None and text:
                structured = json.loads(text)
        except Exception:
            structured = None

        usage = {}
        try:
            if hasattr(response, "usage_metadata"):
                um = response.usage_metadata
                # Attributes might differ slightly in new SDK vs old, check types if possible.
                # Usually: prompt_token_count, candidates_token_count, total_token_count
                usage = {
                    "prompt_token_count": getattr(um, "prompt_token_count", 0),
                    "candidates_token_count": getattr(um, "candidates_token_count", 0),
                    "total_token_count": getattr(um, "total_token_count", 0),
                }
        except Exception:
            usage = {}

        payload: dict[str, Any] = {"text": text, "usage": usage}
        if structured is not None:
            payload["structured"] = structured
        return payload
