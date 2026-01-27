"""Library-owned neutral API payload types.

These types provide a provider-agnostic representation of API parts,
keeping the core decoupled from any vendor SDK types.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import typing

from ._validation import _is_tuple_of, _require
from .turn import Turn


@dataclasses.dataclass(frozen=True, slots=True)
class TextPart:
    """A minimal library-owned representation of a text part.

    Additional part types (e.g., images, files) can be added later while
    keeping the core decoupled from any vendor SDK types.
    """

    text: str

    def __post_init__(self) -> None:
        """Validate TextPart invariants."""
        _require(
            condition=isinstance(self.text, str),
            message="text must be a str",
            exc=TypeError,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class FileRefPart:
    """Provider-agnostic reference to uploaded content."""

    uri: str
    mime_type: str | None = None
    # Preserve raw provider object for advanced use cases
    raw_provider_data: typing.Any = None

    def __post_init__(self) -> None:
        """Validate FileRefPart invariants."""
        _require(
            condition=isinstance(self.uri, str) and self.uri != "",
            message="uri must be a non-empty str",
            exc=TypeError,
        )
        _require(
            condition=self.mime_type is None or isinstance(self.mime_type, str),
            message="mime_type must be a str or None",
            exc=TypeError,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class FileInlinePart:
    """Neutral inline file content for provider-agnostic cache creation.

    Carries raw bytes plus MIME type. Intended for opportunistic creation of
    cached contents where reading the file once at execution time is acceptable.
    """

    mime_type: str
    data: bytes

    def __post_init__(self) -> None:
        """Validate FileInlinePart invariants."""
        _require(
            condition=isinstance(self.mime_type, str) and self.mime_type.strip() != "",
            message="mime_type must be a non-empty str",
            exc=TypeError,
        )
        _require(
            condition=isinstance(self.data, bytes | bytearray),
            message="data must be bytes-like",
            exc=TypeError,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class FilePlaceholder:
    """Placeholder for a local file intended to be uploaded by the provider.

    Handlers replace this with a `FileRefPart` when uploads are supported.
    """

    local_path: Path
    mime_type: str | None = None
    # When True, indicates the local file is ephemeral and may be safely
    # deleted by the pipeline after successful upload. Core stages set this
    # for materialized remote assets; user-provided files should keep the
    # default False to avoid surprises.
    ephemeral: bool = False

    def __post_init__(self) -> None:
        """Validate FilePlaceholder invariants."""
        _require(
            condition=isinstance(self.local_path, Path),
            message="local_path must be a pathlib.Path",
            exc=TypeError,
        )
        _require(
            condition=self.mime_type is None or isinstance(self.mime_type, str),
            message="mime_type must be a str or None",
            exc=TypeError,
        )
        _require(
            condition=isinstance(self.ephemeral, bool),
            message="ephemeral must be a bool",
            exc=TypeError,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class HistoryPart:
    """Structured conversation history to prepend to prompts.

    The pipeline preserves this structured part intact. Provider adapters are
    responsible for rendering it into provider-specific types (e.g., into a
    textual representation when needed). This keeps the planner/handler
    data-centric and decoupled from provider SDK details.
    """

    turns: tuple[Turn, ...]

    def __post_init__(self) -> None:
        """Validate HistoryPart shape."""
        _require(
            condition=_is_tuple_of(self.turns, Turn),
            message="turns must be a tuple[Turn, ...]",
            exc=TypeError,
        )

    @classmethod
    def from_raw_history(cls, raw_turns: typing.Any) -> typing.Self:
        """Validate and normalize raw history data into a HistoryPart.

        Accepted item shapes per turn (strict):
        - Turn instance (used as-is)
        - Mapping with string keys 'question' and 'answer' whose values are str
        - Object with string attributes 'question' and 'answer'

        Empty or None input yields an empty history. Invalid items raise
        ValueError/TypeError with precise index and reason. Both fields cannot
        be empty after stripping whitespace.
        """
        if not raw_turns:
            return cls(turns=())

        validated: list[Turn] = []
        for i, raw in enumerate(raw_turns):
            try:
                if isinstance(raw, Turn):
                    q_val: object | None = raw.question
                    a_val: object | None = raw.answer
                elif isinstance(raw, dict):
                    # Prefer concise structural handling; mapping pattern keeps it clear.
                    q_val = raw.get("question")
                    a_val = raw.get("answer")
                else:
                    q_val = getattr(raw, "question", None)
                    a_val = getattr(raw, "answer", None)

                if not isinstance(q_val, str) or not isinstance(a_val, str):
                    raise TypeError("'question' and 'answer' must be str")
                if q_val == "" and a_val == "":
                    raise ValueError("question and answer cannot both be empty")

                # After the checks above, both are str for type checkers
                validated.append(Turn(question=q_val, answer=a_val))
            except Exception as e:
                raise ValueError(f"Invalid turn at index {i}: {e}") from e

        return cls(turns=tuple(validated))


# Neutral union of API parts; extendable without leaking provider types
type APIPart = TextPart | FileRefPart | FilePlaceholder | HistoryPart | FileInlinePart

# For the minimal slice, a generation config is simply a mapping. We keep it
# library-owned and translate to provider-specific types at the API seam.
GenerationConfigDict = typing.Mapping[str, object]
