"""Extract a v2 ``Output`` from a provider transport response.

This is the v2 boundary's extraction step: it turns a ``ProviderResponse`` into
the immutable ``Output`` facets (text, structured, reasoning, tool calls, usage,
metrics, diagnostics). Continuation is assembled by the execution path and passed
in, since it depends on the request's prior turns.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pollux.interaction.output import (
    Diagnostics,
    Metrics,
    Output,
    Usage,
    completion_status,
)
from pollux.interaction.tools import ToolCall
from pollux.providers.models import provider_response_to_dict

if TYPE_CHECKING:
    from pollux.interaction.continuation import Continuation
    from pollux.interaction.requirements import OutputRequirements
    from pollux.providers.models import ProviderResponse


def _structured_payload(response: ProviderResponse) -> Any:
    """Return the structured payload from a response, parsing text JSON if needed."""
    if response.structured is not None:
        return response.structured
    if response.text:
        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _extract_structured(
    response: ProviderResponse, requirements: OutputRequirements
) -> Any:
    """Extract and (when a model class was requested) validate the structured value."""
    if requirements.output_schema is None:
        return None
    raw = _structured_payload(response)
    model = requirements.output_schema_model()
    if raw is None or model is None:
        return raw
    try:
        return model.model_validate(raw)
    except Exception:
        return None


def provider_response_to_output(
    response: ProviderResponse,
    *,
    requirements: OutputRequirements,
    duration_s: float,
    n_calls: int = 1,
    cache_used: bool = False,
    cache_mode: str = "none",
    cache_hit: bool = False,
    continuation: Continuation | None = None,
    error_category: str | None = None,
) -> Output:
    """Assemble an :class:`Output` from a ``ProviderResponse`` and execution metrics."""
    tool_calls = tuple(
        ToolCall.from_text(id=tc.id, name=tc.name, arguments_text=tc.arguments)
        for tc in (response.tool_calls or [])
    )
    metrics = Metrics(
        duration_s=duration_s,
        n_calls=n_calls,
        cache_used=cache_used,
        cache_mode=cache_mode,
        cache_hit=cache_hit,
        finish_reason=response.finish_reason,
        completion_status=completion_status(
            response.finish_reason, error_category=error_category
        ),
    )
    return Output(
        text=response.text,
        structured=_extract_structured(response, requirements),
        reasoning=response.reasoning,
        tool_calls=tool_calls,
        continuation=continuation,
        usage=Usage.from_dict(response.usage),
        metrics=metrics,
        diagnostics=Diagnostics(raw={"response": provider_response_to_dict(response)}),
    )
