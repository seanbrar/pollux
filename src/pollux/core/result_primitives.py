"""Result Monad for Robust Error Handling.

Implements the "Unified Result Type" enhancement for explicit error handling.
This prevents the need for broad try/except blocks in the executor and makes
failures a predictable part of the data flow.
"""

from __future__ import annotations

import dataclasses
import typing

TSuccess = typing.TypeVar("TSuccess")
TFailure = typing.TypeVar("TFailure", bound=Exception)


@dataclasses.dataclass(frozen=True, slots=True)
class Success[TSuccess]:
    """A successful result in the pipeline."""

    value: TSuccess


@dataclasses.dataclass(frozen=True, slots=True)
class Failure[TFailure]:
    """A failure in the pipeline, containing the error."""

    error: TFailure


Result = Success[TSuccess] | Failure[TFailure]
