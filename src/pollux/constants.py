"""Project-wide constants for Gemini Batch Processing Framework"""  # noqa: D415

# ==============================================================================
# File Processing Configuration
# ==============================================================================

# File size limits (in bytes)
_MB = 1024 * 1024
_GB = 1024 * _MB

MAX_FILE_SIZE = 100 * _MB  # General file size limit

# Inline caching payload safety guard (read bound when creating explicit caches)
# Conservative default to avoid large I/O spikes when caching is enabled.
INLINE_CACHE_MAX_BYTES = 16 * _MB

# ==============================================================================
# Batch Processing Configuration
# ==============================================================================

TARGET_EFFICIENCY_RATIO = 3.0  # Minimum efficiency improvement target

# ==============================================================================
# Visualization Configuration
# ==============================================================================

# Figure dimensions
VIZ_FIGURE_SIZE = (15, 10)
VIZ_SCALING_FIGURE_SIZE = (15, 6)

# Styling
VIZ_ALPHA = 0.8
VIZ_BAR_WIDTH = 0.35

# Color scheme
VIZ_COLORS = {
    "individual": "#ff7f7f",
    "batch": "#7fbf7f",
    "improvements": ["#4CAF50", "#2196F3", "#FF9800"],
    "line": "#2E7D32",
}
