"""The Pollux v2 canonical interaction model.

These are the application-facing primitives for the v2 mental model::

    Environment + Input + Config -> Output

The types here are frozen dataclasses with no behavior beyond construction,
validation, and serialization. The live ``run()`` / ``run_many()`` pipeline does
not use them yet; the provider boundary is migrated onto them in Slice 2. They
are not re-exported from the top-level ``pollux`` package until the Slice 3
frontdoor cutover.
"""

from __future__ import annotations

from pollux.interaction.collection import CollectionStatus, OutputCollection
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.environment import (
    CachePolicy,
    CacheSetting,
    Environment,
    EnvironmentSnapshot,
)
from pollux.interaction.event import Event, EventType
from pollux.interaction.input import Input
from pollux.interaction.output import (
    CompletionStatus,
    Diagnostics,
    Metrics,
    Output,
    Usage,
    completion_status,
)
from pollux.interaction.requirements import OutputRequirements, ToolChoice
from pollux.interaction.tools import (
    JSONValue,
    ToolCall,
    ToolCallDelta,
    ToolDeclaration,
    ToolResult,
)

__all__ = [
    "CachePolicy",
    "CacheSetting",
    "CollectionStatus",
    "CompletionStatus",
    "Continuation",
    "Diagnostics",
    "Environment",
    "EnvironmentSnapshot",
    "Event",
    "EventType",
    "Input",
    "JSONValue",
    "Message",
    "Metrics",
    "Output",
    "OutputCollection",
    "OutputRequirements",
    "ToolCall",
    "ToolCallDelta",
    "ToolChoice",
    "ToolDeclaration",
    "ToolResult",
    "Usage",
    "completion_status",
]
