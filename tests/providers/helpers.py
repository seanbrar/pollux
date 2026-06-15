"""Provider test helpers."""

from __future__ import annotations

from typing import Any


async def async_return(value: Any) -> Any:
    """Wrap a value in a coroutine for use as an async fake."""
    return value


class FakeResponses:
    """Captures kwargs passed to responses.create()."""

    def __init__(
        self, *, status: str = "completed", incomplete_reason: str | None = None
    ) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self._status = status
        self._incomplete_reason = incomplete_reason

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        incomplete_details = (
            type("IncompleteDetails", (), {"reason": self._incomplete_reason})()
            if self._incomplete_reason is not None
            else None
        )
        return type(
            "Response",
            (),
            {
                "output_text": "ok",
                "usage": None,
                "id": None,
                "output": [],
                "status": self._status,
                "incomplete_details": incomplete_details,
            },
        )()
