"""Provider-specific token estimation protocol.

Concise contract for adapters that estimate token usage for resolved
`Source` objects.

Requirements (must):
- Be pure and deterministic (no I/O, no randomness, no SDK calls)
- Never invoke `content_loader` on `Source`
- Accept missing optional metadata without raising

Guidelines (should):
- Use only cheap metadata (e.g., `source_type`, `mime_type`, `size_bytes`)
- Aggregate by summing bounds and combining confidence with a simple rule
- Keep implementation small and testable
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pollux.core.types import Source, TokenEstimate


@runtime_checkable
class EstimationAdapter(Protocol):
    """Protocol for provider-specific token estimation."""

    @property
    def provider(self) -> str:  # pragma: no cover - trivial
        """Return provider identifier (for example, 'gemini')."""
        ...

    def estimate(self, source: Source) -> TokenEstimate:
        """Estimate tokens for a single `Source`.

        - Must be pure (no I/O) and deterministic
        - Must not read content (do not call `content_loader`)
        - Must tolerate incomplete metadata by falling back to conservative heuristics
        """
        ...

    def aggregate(self, estimates: list[TokenEstimate]) -> TokenEstimate:
        """Aggregate multiple estimates into a total.

        - Should sum min/expected/max across inputs
        - Should combine confidence with a simple, explicit rule
        - Must remain pure (no I/O)
        """
        ...
