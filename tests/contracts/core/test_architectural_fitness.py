import inspect
import logging

import pytest

from pollux.core import exceptions, models, types

logger = logging.getLogger(__name__)


class TestArchitecturalFitnessFunction:
    """Meta-test that evaluates overall architectural quality."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_architectural_compliance_score(self):
        """Evaluate the overall architectural compliance of the core module."""
        scores = {
            "simplicity": self._calculate_simplicity_score(),
            "clarity": self._calculate_clarity_score(),
            "robustness": self._calculate_robustness_score(),
            "maintainability": self._calculate_maintainability_score(),
        }

        # All criteria should score "Good" (3) or better
        for criterion, score in scores.items():
            assert score >= 3, f"{criterion} scored {score}/5 - needs improvement"

        # Overall score should be "Good" (3.5) or better
        average_score = sum(scores.values()) / len(scores)
        assert average_score >= 3.5, f"Overall architecture score: {average_score}/5"

        logger.info("Architectural Compliance Scores:")
        for criterion, score in scores.items():
            logger.info(f"  {criterion}: {score}/5")
        logger.info(f"  Overall: {average_score:.1f}/5")

    def _calculate_simplicity_score(self) -> int:
        """Calculate simplicity score (1-5)."""
        score = 5

        # Deduct points for complexity
        dataclasses = [
            types.Success,
            types.Failure,
            types.Turn,
            types.Source,
            types.InitialCommand,
            types.ResolvedCommand,
            models.RateLimits,
            models.CachingCapabilities,
            models.ModelCapabilities,
        ]

        for cls in dataclasses:
            sig = inspect.signature(cls)
            param_count = len(sig.parameters) - 1  # Exclude self
            if param_count > 6:
                score -= 1
                break

        return max(1, score)

    def _calculate_clarity_score(self) -> int:
        """Calculate clarity score (1-5)."""
        score = 5

        # Check for missing docstrings
        modules = [types, models, exceptions]
        for module in modules:
            public_items = [
                name
                for name in dir(module)
                if not name.startswith("_")
                and not inspect.ismodule(getattr(module, name))
            ]

            for item_name in public_items:
                item = getattr(module, item_name)
                if (
                    inspect.isclass(item) or inspect.isfunction(item)
                ) and not item.__doc__:
                    score -= 1
                    break

        return max(1, score)

    def _calculate_robustness_score(self) -> int:
        """Calculate robustness score (1-5)."""
        score = 5

        # Check if dataclasses are frozen
        dataclasses = [
            types.Success,
            types.Failure,
            types.Turn,
            types.Source,
            types.InitialCommand,
            types.ResolvedCommand,
            models.RateLimits,
            models.CachingCapabilities,
            models.ModelCapabilities,
        ]

        for cls in dataclasses:
            if (
                hasattr(cls, "__dataclass_params__")
                and not cls.__dataclass_params__.frozen
            ):
                score -= 1
                break

        return max(1, score)

    def _calculate_maintainability_score(self) -> int:
        """Calculate maintainability score (1-5)."""
        score = 5

        # Check for logical module organization
        if not any("Command" in item for item in dir(types)):
            score -= 1

        if not any("Model" in item for item in dir(models)):
            score -= 1

        if not any(
            "Error" in item for item in dir(exceptions) if not item.startswith("_")
        ):
            score -= 1

        return max(1, score)
