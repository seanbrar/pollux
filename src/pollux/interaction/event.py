"""``Event``: the incremental form of an interaction output.

Streaming is not a separate semantic mode. It is a different timeline for
observing the same interaction: the events below carry the partial signal, and a
successful stream ends in a single ``done`` event whose ``output`` is the same
:class:`~pollux.interaction.output.Output` non-streaming execution would return.

Consumers match on ``Event.type`` and never parse SSE, provider SDK chunks, or
``delta.tool_calls`` fragments — Pollux normalizes those into the vocabulary
here and assembles tool-call fragments into final :class:`ToolCall` objects.

Terminal stream errors raise from the iterator (the wrapped provider error)
rather than emitting a ``done`` event, so a failed interaction never yields a
final output. A dedicated ``error`` event with recoverable/terminal
classification is deliberately deferred until a provider needs mid-stream
recoverable errors; adding it later is additive, not breaking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pollux.interaction.output import Output, Usage
    from pollux.interaction.tools import ToolCall, ToolCallDelta

#: The streamed event vocabulary. ``start`` opens the stream; ``text_delta`` and
#: ``reasoning_delta`` carry visible/reasoning text; ``tool_call_delta`` carries
#: a partial tool-call fragment and ``tool_call`` a completed normalized call;
#: ``usage`` reports a usage update when the provider streams one; ``finish``
#: carries the provider finish reason; ``done`` carries the final assembled
#: output.
EventType = Literal[
    "start",
    "text_delta",
    "reasoning_delta",
    "tool_call_delta",
    "tool_call",
    "usage",
    "finish",
    "done",
]


@dataclass(frozen=True, slots=True)
class Event:
    """One event in the timeline of a streamed interaction.

    Only the facet relevant to ``type`` is set: ``text`` for ``text_delta`` /
    ``reasoning_delta``, ``delta`` for ``tool_call_delta``, ``tool_call`` for
    ``tool_call``, ``usage`` for ``usage``, ``finish_reason`` for ``finish``, and
    ``output`` for ``done``.
    """

    type: EventType
    text: str = ""
    delta: ToolCallDelta | None = None
    tool_call: ToolCall | None = None
    usage: Usage | None = None
    finish_reason: str | None = None
    output: Output | None = None
