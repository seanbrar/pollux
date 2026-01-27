"""Public type aliases and re-exports for end-users.

This module provides a clear, stable surface for common data types without
exposing internal pipeline mechanics.

Example:
    ```python
    from pollux import run_simple, types

    # Analyze a file with a single prompt
    result = await run_simple(
        "Summarize this document",
        source=types.Source.from_file("document.pdf"),
        options=types.make_execution_options(result_prefer_json_array=True),
    )
    print(result["answers"][0])
    ```

See Also:
    For convenience functions, use `run_simple()` and `run_batch()` from the main module.
    For advanced pipeline construction, see the individual type documentation.
"""

from __future__ import annotations

from pollux.core.execution_options import (
    CacheOptions,
    CachePolicyHint,
    EstimationOptions,
    ExecutionOptions,
    RemoteFilePolicy,
    ResultOption,
    make_execution_options,
)
from pollux.core.sources import sources_from_directory
from pollux.core.types import ResultEnvelope, Source, TokenEstimate, Turn

__all__ = [  # noqa: RUF022
    # "Everyday" types
    "Source",
    "sources_from_directory",
    "Turn",
    "ResultEnvelope",
    "TokenEstimate",
    # Options
    "ExecutionOptions",
    "CacheOptions",
    "CachePolicyHint",
    "EstimationOptions",
    "RemoteFilePolicy",
    "ResultOption",
    "make_execution_options",
]
