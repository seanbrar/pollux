import pytest

from pollux.config import resolve_config
from pollux.core.concurrency import resolve_request_concurrency
from pollux.core.execution_options import make_execution_options


@pytest.mark.unit
def test_n_calls_le_zero_returns_one() -> None:
    cfg = resolve_config(overrides={"request_concurrency": 6})
    assert (
        resolve_request_concurrency(
            n_calls=0, options=None, cfg=cfg, rate_constrained=False
        )
        == 1
    )
    assert (
        resolve_request_concurrency(
            n_calls=-5, options=None, cfg=cfg, rate_constrained=False
        )
        == 1
    )


@pytest.mark.unit
def test_rate_constrained_forces_one() -> None:
    cfg = resolve_config(overrides={"request_concurrency": 8})
    opts = make_execution_options(request_concurrency=10)
    assert (
        resolve_request_concurrency(
            n_calls=7, options=opts, cfg=cfg, rate_constrained=True
        )
        == 1
    )


@pytest.mark.unit
def test_options_override_wins_when_positive() -> None:
    cfg = resolve_config(overrides={"request_concurrency": 9})
    opts = make_execution_options(request_concurrency=3)
    assert (
        resolve_request_concurrency(
            n_calls=10, options=opts, cfg=cfg, rate_constrained=False
        )
        == 3
    )


@pytest.mark.unit
def test_config_default_used_when_no_option_or_zero() -> None:
    cfg = resolve_config(overrides={"request_concurrency": 4})
    opts_zero = make_execution_options(request_concurrency=0)
    assert (
        resolve_request_concurrency(
            n_calls=10, options=opts_zero, cfg=cfg, rate_constrained=False
        )
        == 4
    )
    assert (
        resolve_request_concurrency(
            n_calls=2, options=None, cfg=cfg, rate_constrained=False
        )
        == 4
    )


@pytest.mark.unit
def test_unbounded_defaults_to_n_calls_when_no_bounds() -> None:
    cfg = resolve_config(overrides={"request_concurrency": 0})
    # options without request_concurrency set
    opts = make_execution_options()
    assert (
        resolve_request_concurrency(
            n_calls=5, options=opts, cfg=cfg, rate_constrained=False
        )
        == 5
    )
