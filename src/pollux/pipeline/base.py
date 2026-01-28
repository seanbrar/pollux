"""Base protocol for pipeline handlers.

Public surface area intentionally minimal: extension authors implement
``BaseAsyncHandler``. Type-erasure mechanics used by the executor are
internal and live in ``pipeline._erasure``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, TypeVar

from pollux.core.exceptions import PolluxError

if TYPE_CHECKING:
    from pollux.core.types import Result

log = logging.getLogger(__name__)

# Contravariant input (handlers accept supertypes), invariant output and error
T_In = TypeVar("T_In", contravariant=True)
T_Out = TypeVar("T_Out")
T_Error = TypeVar("T_Error", bound=PolluxError)


class BaseAsyncHandler(Protocol[T_In, T_Out, T_Error]):
    """Protocol for asynchronous pipeline handlers.

    Each handler performs a single transformation on the command object,
    making it easy to test and reason about.
    """

    async def handle(self, command: T_In) -> Result[T_Out, T_Error]:
        """Process a command object.

        Args:
            command: The input command state from the previous pipeline stage.

        Returns:
            A Result object containing either the next command state or an error.
        """
        ...


if TYPE_CHECKING:  # pragma: no cover - typing only
    from typing import Never

    from pollux.core.types import FinalizedCommand, ResultEnvelope

    class BuildsEnvelope(Protocol):
        """Protocol for terminal stages that produce a ResultEnvelope.

        This is a typing-only contract used by tooling and documentation to
        signal that the final pipeline stage must construct the user-facing
        ResultEnvelope in a Success result.
        """

        async def handle(
            self, cmd: FinalizedCommand
        ) -> Result[ResultEnvelope, Never]:  # pragma: no cover - typing only
            """Process the finalized command and return a ResultEnvelope."""
            ...


# Public surface: keep the handler protocol as the only explicit export
__all__ = ("BaseAsyncHandler",)
