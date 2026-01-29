"""Contract compliance tests for the configuration system."""

import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config
from pollux.core.exceptions import ConfigurationError


@pytest.mark.contract
def test_error_handling_is_explicit_for_missing_api_key() -> None:
    """Contract: use_real_api=True without api_key raises ConfigurationError."""
    with (
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ConfigurationError) as exc_info,
    ):
        resolve_config(overrides={"use_real_api": True})

    assert "api_key" in str(exc_info.value).lower()
