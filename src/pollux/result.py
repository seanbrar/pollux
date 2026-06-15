"""The v1 ``ResultEnvelope`` type.

The v1 realtime/deferred pipelines that built envelopes were removed in the v2
cutover; the v2 path returns ``Output`` / ``OutputCollection`` instead. This
``TypedDict`` is retained because ``Options.continue_from`` and serialized
conversation state still reference the v1 envelope shape until the public v1
surface is removed.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ResultEnvelope(TypedDict, total=False):
    """Standard result envelope returned by Pollux v1.

    ``status`` is ``"ok"`` when all answers are non-empty, ``"partial"`` when
    some are empty, or ``"error"`` when all are empty.
    """

    status: Literal["ok", "partial", "error"]
    answers: list[str]  # Stable core contract.
    #: Present only when ``response_schema`` was set in Options.
    structured: list[Any]
    reasoning: list[str | None]
    #: Heuristic: ``0.9`` for ``"ok"`` status, ``0.5`` otherwise.
    confidence: float
    #: Always ``"text"`` in v1.0.
    extraction_method: str
    usage: dict[str, int]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    _conversation_state: dict[str, Any]
    tool_calls: list[list[dict[str, Any]]]
