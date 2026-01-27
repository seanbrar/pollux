"""Research and benchmarking utilities for pollux.

Progressive disclosure: advanced users can import from this namespace
without bloating the top-level API surface.
"""

from __future__ import annotations

__all__ = [
    "EfficiencyReport",
    "compare_efficiency",
]

from .efficiency import EfficiencyReport, compare_efficiency
