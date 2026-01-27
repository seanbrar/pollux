"""Visualization utilities for batch processing analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypedDict

from pollux.constants import (
    TARGET_EFFICIENCY_RATIO,
    VIZ_ALPHA,
    VIZ_BAR_WIDTH,
    VIZ_COLORS,
    VIZ_FIGURE_SIZE,
    VIZ_SCALING_FIGURE_SIZE,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    import pandas as pd

# Constants for consistent styling
COLORS = VIZ_COLORS


# -----------------------------
# Public result data structures
# -----------------------------


class MetricSet(TypedDict):
    """Basic metric set for individual or batch runs."""

    calls: int
    tokens: int
    time: float


class Metrics(TypedDict):
    """Container of metric sets."""

    individual: MetricSet
    batch: MetricSet


class Efficiency(TypedDict):
    """Efficiency stats derived from metrics."""

    token_efficiency_ratio: float
    time_efficiency: float
    meets_target: bool


class EfficiencyResults(TypedDict):
    """Shape expected by visualization helpers."""

    metrics: Metrics
    efficiency: Efficiency


class ScalingDataItem(TypedDict):
    """One row of scaling analysis input."""

    questions: int
    efficiency: float
    individual_tokens: int
    batch_tokens: int
    meets_target: NotRequired[bool]


# Explicit public API
__all__ = [
    "EfficiencyResults",
    "PlotConfig",
    "ScalingDataItem",
    "create_efficiency_visualizations",
    "create_focused_efficiency_visualization",
    "run_efficiency_experiment",
    "visualize_scaling_results",
]


class PlotConfig(TypedDict):
    """Typed configuration for plotting parameters used in this module."""

    alpha: float
    bar_width: float
    figure_size: tuple[int, int]
    scaling_figure_size: tuple[int, int]
    target_efficiency: float


PLOT_CONFIG: PlotConfig = {
    "alpha": float(VIZ_ALPHA),
    "bar_width": float(VIZ_BAR_WIDTH),
    "figure_size": (int(VIZ_FIGURE_SIZE[0]), int(VIZ_FIGURE_SIZE[1])),
    "scaling_figure_size": (
        int(VIZ_SCALING_FIGURE_SIZE[0]),
        int(VIZ_SCALING_FIGURE_SIZE[1]),
    ),
    "target_efficiency": float(TARGET_EFFICIENCY_RATIO),
}


Numeric = float | int


def _format_integer(x: Numeric) -> str:
    """Format a value as an integer."""
    return f"{int(x)}"


def _format_integer_with_commas(x: Numeric) -> str:
    """Format an integer with comma separators."""
    return f"{int(x):,}"


def _format_time_seconds(x: Numeric) -> str:
    """Format a value as seconds with two decimals."""
    return f"{x:.2f}s"


def _format_efficiency_multiplier(x: Numeric) -> str:
    """Format an efficiency multiplier with one decimal place."""
    return f"{x:.1f}×"  # noqa: RUF001


def _add_bar_annotations(
    ax: Any,
    bars: Iterable[Any],
    values: list[Numeric],
    format_func: Callable[[Numeric], str] | None = None,
) -> None:
    """Add value annotations to bar charts."""
    if format_func is None:
        format_func = _format_integer

    max_val = max(values) if values else 1

    for bar, value in zip(bars, values, strict=False):
        height = bar.get_height()
        offset = max_val * 0.01
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + offset,
            format_func(value),
            ha="center",
            va="bottom",
            fontweight="bold",
        )


def _create_comparison_subplot(
    ax: Any,
    title: str,
    ylabel: str,
    methods: list[str],
    values: list[Numeric],
    format_func: Callable[[Numeric], str] | None = None,
) -> None:
    """Create a standardized comparison bar chart."""
    colors = [COLORS["individual"], COLORS["batch"]]
    bars = ax.bar(methods, values, color=colors, alpha=PLOT_CONFIG["alpha"])
    ax.set_title(title, fontweight="bold")
    ax.set_ylabel(ylabel)

    _add_bar_annotations(ax, bars, values, format_func)


def _validate_results_data(results: dict[str, Any]) -> bool:
    """Validate that results contain the required shape."""
    required_keys = ["metrics", "efficiency"]
    if not all(key in results for key in required_keys):
        return False

    metrics = results["metrics"]
    return all(key in metrics for key in ["individual", "batch"])


# ---------------------------
# Lightweight pure utilities
# ---------------------------


def summarize_efficiency(results: EfficiencyResults) -> dict[str, float]:
    """Compute a compact summary for display or testing.

    Returns keys: ``token_efficiency``, ``time_efficiency``, ``cost_reduction_pct``,
    and ``api_call_reduction``.
    """
    indiv = results["metrics"]["individual"]
    batch = results["metrics"]["batch"]
    eff = results["efficiency"]
    token_eff = float(eff["token_efficiency_ratio"]) or 1.0
    time_eff = float(eff["time_efficiency"]) or 1.0
    api_call_reduction = (indiv["calls"] / batch["calls"]) if batch["calls"] else 1.0
    # Cost roughly proportional to tokens for most tiers
    cost_reduction_pct = (1 - 1 / token_eff) * 100 if token_eff else 0.0
    return {
        "token_efficiency": token_eff,
        "time_efficiency": time_eff,
        "cost_reduction_pct": cost_reduction_pct,
        "api_call_reduction": api_call_reduction,
    }


def _require_matplotlib() -> Any:
    """Lazy-import matplotlib for environments without viz extras installed."""
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - exercised in notebook usage
        raise RuntimeError(
            "matplotlib is required for visualization. Install with 'gemini-batch[viz]'."
        ) from exc
    return plt


def _require_pandas() -> Any:
    """Lazy-import pandas for environments without viz extras installed."""
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - exercised in notebook usage
        raise RuntimeError(
            "pandas is required for visualization. Install with 'gemini-batch[viz]'."
        ) from exc
    return pd


def create_efficiency_visualizations(
    results: EfficiencyResults,
    *,
    show: bool = True,
) -> None:
    """Create comprehensive visualizations of efficiency gains.

    Returns the ``(fig, ((ax1, ax2), (ax3, ax4)))`` tuple for further customization.
    Set ``show=False`` to suppress ``plt.show()`` in scripts.
    """
    plt = _require_matplotlib()
    if not _validate_results_data(results):  # type: ignore
        print("❌ Invalid results data structure")  # noqa: T201
        return None

    individual_metrics = results["metrics"]["individual"]
    batch_metrics = results["metrics"]["batch"]
    efficiency = results["efficiency"]

    # Create figure with subplots
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(
        2,
        2,
        figsize=PLOT_CONFIG["figure_size"],
    )
    fig.suptitle(
        "Gemini Batch Processing Efficiency Analysis",
        fontsize=16,
        fontweight="bold",
    )

    methods = ["Individual", "Batch"]

    # 1. API Calls Comparison
    calls = [individual_metrics["calls"], batch_metrics["calls"]]
    _create_comparison_subplot(
        ax1,
        "API Calls Required",
        "Number of Calls",
        methods,
        calls,  # type: ignore
    )

    # 2. Token Usage Comparison
    tokens = [individual_metrics["tokens"], batch_metrics["tokens"]]
    _create_comparison_subplot(
        ax2,
        "Total Token Usage",
        "Tokens",
        methods,
        tokens,  # type: ignore
        format_func=_format_integer_with_commas,
    )

    # 3. Processing Time Comparison
    times = [individual_metrics["time"], batch_metrics["time"]]
    _create_comparison_subplot(
        ax3,
        "Processing Time",
        "Time (seconds)",
        methods,
        times,
        format_func=_format_time_seconds,
    )

    # 4. Efficiency Improvements
    improvements = [
        efficiency["token_efficiency_ratio"],
        efficiency["time_efficiency"],
        individual_metrics["calls"] / batch_metrics["calls"],
    ]
    improvement_labels = [
        "Token\nEfficiency",
        "Time\nEfficiency",
        "API Call\nReduction",
    ]

    bars4 = ax4.bar(
        improvement_labels,
        improvements,
        color=COLORS["improvements"],
        alpha=PLOT_CONFIG["alpha"],
    )
    ax4.set_title("Efficiency Improvements (×)", fontweight="bold")  # noqa: RUF001
    ax4.set_ylabel("Improvement Factor")
    ax4.axhline(
        y=PLOT_CONFIG["target_efficiency"],
        color="red",
        linestyle="--",
        alpha=0.7,
        label="Target (3x)",
    )
    ax4.legend()

    _add_bar_annotations(ax4, bars4, improvements, _format_efficiency_multiplier)

    plt.tight_layout()
    if show:
        plt.show()

    # Summary statistics
    _print_efficiency_summary(individual_metrics, batch_metrics, efficiency)  # type: ignore
    return fig, ((ax1, ax2), (ax3, ax4))  # type: ignore


def _print_efficiency_summary(
    individual_metrics: dict[str, Any],
    batch_metrics: dict[str, Any],
    efficiency: dict[str, Any],
) -> None:
    """Print a formatted efficiency summary."""
    print("\n📊 EFFICIENCY SUMMARY:")  # noqa: T201
    print(  # noqa: T201
        f"🎯 Token efficiency improvement: "
        f"{efficiency['token_efficiency_ratio']:.1f}× "  # noqa: RUF001
        f"(Target: {PLOT_CONFIG['target_efficiency']}×+)",  # noqa: RUF001
    )
    print(f"⚡ Time efficiency improvement: {efficiency['time_efficiency']:.1f}×")  # noqa: RUF001, T201

    cost_reduction = (1 - 1 / efficiency["token_efficiency_ratio"]) * 100
    print(f"💰 Estimated cost reduction: {cost_reduction:.1f}%")  # noqa: T201

    tokens_saved = individual_metrics["tokens"] - batch_metrics["tokens"]
    if tokens_saved > 0:
        reduction_pct = tokens_saved / individual_metrics["tokens"] * 100
        print(f"🔢 Tokens saved: {tokens_saved:,} ({reduction_pct:.1f}% reduction)")  # noqa: T201


def visualize_scaling_results(
    scaling_data: list[ScalingDataItem], *, show: bool = True
) -> None:
    """Visualize how efficiency scales with question count."""
    plt = _require_matplotlib()
    pd = _require_pandas()
    if not scaling_data:
        print("❌ No scaling data available for visualization")  # noqa: T201
        return

    # Validate data structure
    required_fields = ["questions", "efficiency", "individual_tokens", "batch_tokens"]
    if not all(field in scaling_data[0] for field in required_fields):
        print("❌ Invalid scaling data structure")  # noqa: T201
        return

    # Convert to DataFrame for easier plotting
    df = pd.DataFrame(scaling_data)

    # Create visualization
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=PLOT_CONFIG["scaling_figure_size"])
    fig.suptitle("Batch Processing Efficiency Scaling", fontsize=16, fontweight="bold")

    # 1. Efficiency vs Question Count
    ax1.plot(
        df["questions"],
        df["efficiency"],
        "o-",
        linewidth=3,
        markersize=8,
        color=COLORS["line"],
    )
    ax1.axhline(
        y=PLOT_CONFIG["target_efficiency"],
        color="red",
        linestyle="--",
        alpha=0.7,
        label="Target (3×)",  # noqa: RUF001
    )
    ax1.set_xlabel("Number of Questions")
    ax1.set_ylabel("Efficiency Improvement (×)")  # noqa: RUF001
    ax1.set_title("Efficiency vs Question Count")
    ax1.grid(True, alpha=0.3)  # noqa: FBT003
    ax1.legend()

    # Add annotations for each point
    for _, row in df.iterrows():
        ax1.annotate(
            f"{row['efficiency']:.1f}×",  # noqa: RUF001
            (row["questions"], row["efficiency"]),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontweight="bold",
        )

    # 2. Token Usage Comparison
    x_pos = range(len(df))
    width = PLOT_CONFIG["bar_width"]

    ax2.bar(
        [x - width / 2 for x in x_pos],
        df["individual_tokens"],
        width,
        label="Individual",
        color=COLORS["individual"],
        alpha=PLOT_CONFIG["alpha"],
    )
    ax2.bar(
        [x + width / 2 for x in x_pos],
        df["batch_tokens"],
        width,
        label="Batch",
        color=COLORS["batch"],
        alpha=PLOT_CONFIG["alpha"],
    )

    ax2.set_xlabel("Question Count")
    ax2.set_ylabel("Total Tokens")
    ax2.set_title("Token Usage: Individual vs Batch")
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(df["questions"])
    ax2.legend()
    ax2.grid(True, alpha=0.3)  # noqa: FBT003

    plt.tight_layout()
    if show:
        plt.show()

    # Summary insights
    _print_scaling_insights(df)


def _print_scaling_insights(df: pd.DataFrame) -> None:
    """Print formatted scaling insights."""
    print("\n🎯 SCALING INSIGHTS:")  # noqa: T201
    max_efficiency = df["efficiency"].max()
    best_q_count = df.loc[df["efficiency"].idxmax(), "questions"]

    print(  # noqa: T201
        f"📈 Maximum efficiency: {max_efficiency:.1f}× (with {best_q_count} questions)",  # noqa: RUF001
    )

    if "meets_target" in df.columns:
        target_count = sum(df["meets_target"])
        print(f"🎯 Questions meeting 3× target: {target_count}/{len(df)}")  # noqa: RUF001, T201

    if len(df) >= 2:
        efficiency_trend = df["efficiency"].iloc[-1] - df["efficiency"].iloc[0]
        trend_direction = "+" if efficiency_trend > 0 else ""
        print(  # noqa: T201
            f"📊 Efficiency trend: {trend_direction}{efficiency_trend:.1f}× "  # noqa: RUF001
            f"from {df['questions'].min()} to {df['questions'].max()} questions",
        )


def _format_metrics_table(metrics_data: list[tuple[str, Any, Any, str]]) -> None:
    """Format and print a metrics comparison table."""
    print("\n📊 EFFICIENCY RESULTS:")  # noqa: T201
    print(f"{'Metric':<25} {'Individual':<12} {'Batch':<12} {'Improvement':<12}")  # noqa: T201
    print("-" * 65)  # noqa: T201

    for metric_name, individual_val, batch_val, improvement in metrics_data:
        print(f"{metric_name:<25} {individual_val:<12} {batch_val:<12} {improvement}")  # noqa: T201


class TextQuestionProcessor(Protocol):
    """Protocol for processors that can answer lists of questions over text."""

    def process_text_questions(
        self, content: str, questions: list[str], *, compare_methods: bool = ...
    ) -> dict[str, Any]:
        """Process `questions` over `content`, optionally comparing methods."""


def run_efficiency_experiment(
    processor: TextQuestionProcessor,
    content: str,
    questions: list[str],
    name: str = "Demo",
) -> dict[str, Any]:
    """Run a comprehensive efficiency experiment with visualizations."""
    # Only import plotting when we actually visualize later
    print(f"🔬 Running Experiment: {name}")  # noqa: T201
    print("=" * 50)  # noqa: T201

    # Process with comparison enabled
    results = processor.process_text_questions(content, questions, compare_methods=True)

    if not _validate_results_data(results):
        print("❌ Experiment failed - invalid results")  # noqa: T201
        return {}

    # Extract metrics
    individual_metrics = results["metrics"]["individual"]
    batch_metrics = results["metrics"]["batch"]
    efficiency = results["efficiency"]

    # Prepare metrics for table display
    metrics_data = [
        (
            "API Calls",
            individual_metrics["calls"],
            batch_metrics["calls"],
            f"{individual_metrics['calls'] / batch_metrics['calls']:.1f}x",
        ),
        (
            "Total Tokens",
            individual_metrics["tokens"],
            f"{batch_metrics['tokens']:,}",
            f"{efficiency['token_efficiency_ratio']:.1f}x",
        ),
        (
            "Processing Time",
            f"{individual_metrics['time']:.2f}s",
            f"{batch_metrics['time']:.2f}s",
            f"{efficiency['time_efficiency']:.1f}x",
        ),
    ]

    _format_metrics_table(metrics_data)

    # Target analysis
    target_met = "✅ YES" if efficiency["meets_target"] else "❌ NO"
    print(f"{'Meets 3x Target':<25} {target_met}")  # noqa: T201

    return results


def create_focused_efficiency_visualization(
    results: dict[str, Any],
    show_summary: bool = False,  # noqa: FBT001, FBT002
    *,
    show: bool = True,
) -> None:
    """Create focused 2-chart visualization for notebook demonstrations."""
    plt = _require_matplotlib()
    if not _validate_results_data(results):
        print("❌ Invalid results data structure")  # noqa: T201
        return

    individual_metrics = results["metrics"]["individual"]
    batch_metrics = results["metrics"]["batch"]
    efficiency = results["efficiency"]

    # Create side-by-side layout
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Batch Processing Efficiency Analysis", fontsize=16, fontweight="bold")

    methods = ["Individual", "Batch"]

    # 1. Token Usage Comparison (main value proposition)
    tokens = [individual_metrics["tokens"], batch_metrics["tokens"]]
    _create_comparison_subplot(
        ax1,
        "Total Token Usage",
        "Tokens",
        methods,
        tokens,
        format_func=_format_integer_with_commas,
    )

    # Add more headroom by extending y-axis limits
    max_tokens = max(tokens)
    ax1.set_ylim(0, max_tokens * 1.3)  # 30% more headroom

    # 2. Processing Time Comparison (workflow benefit)
    times = [individual_metrics["time"], batch_metrics["time"]]
    _create_comparison_subplot(
        ax2,
        "Processing Time",
        "Time (seconds)",
        methods,
        times,
        format_func=_format_time_seconds,
    )

    # Add more headroom by extending y-axis limits
    max_times = max(times)
    ax2.set_ylim(0, max_times * 1.3)  # 30% more headroom

    # Add efficiency annotations to make impact clear
    token_efficiency = efficiency["token_efficiency_ratio"]
    time_efficiency = efficiency["time_efficiency"]

    # Add efficiency callout on token chart (moved higher up)
    ax1.text(
        0.5,
        0.9,
        f"{token_efficiency:.1f}× more efficient",  # noqa: RUF001
        ha="center",
        transform=ax1.transAxes,
        fontsize=12,
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "lightgreen", "alpha": 0.7},
    )

    # Add time savings callout (moved higher up)
    ax2.text(
        0.5,
        0.9,
        f"{time_efficiency:.1f}× faster",  # noqa: RUF001
        ha="center",
        transform=ax2.transAxes,
        fontsize=12,
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "lightblue", "alpha": 0.7},
    )

    plt.tight_layout()
    if show:
        plt.show()

    # Optional summary (concise version)
    if show_summary:
        tokens_saved = individual_metrics["tokens"] - batch_metrics["tokens"]
        cost_reduction = (tokens_saved / individual_metrics["tokens"]) * 100
        print(f"\n💰 Cost reduction: {cost_reduction:.1f}%")  # noqa: T201
        print(f"⚡ Time savings: {time_efficiency:.1f}× faster")  # noqa: RUF001, T201
        print(f"🎯 Target met: {'Yes' if efficiency['meets_target'] else 'No'}")  # noqa: T201
