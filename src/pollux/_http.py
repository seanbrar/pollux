"""Small HTTP-related constants shared across Pollux.

This module is intentionally tiny to avoid circular imports and drift.
"""

from __future__ import annotations

# Retryable status codes shared by provider mapping and core retry.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 409, 429, 500, 502, 503, 504})
