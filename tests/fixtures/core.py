"""Core, always-on test fixtures and hooks.

Includes environment isolation, logging, marker registration, and common
utilities. Loaded as a pytest plugin from the root conftest.
"""

from __future__ import annotations

from contextlib import suppress
import logging
import os

import pytest


# --- Environment Isolation (Autouse) ---
@pytest.fixture(autouse=True)
def block_dotenv(request, monkeypatch):
    """Prevent python-dotenv from loading project .env files during tests.

    Opt-in escape hatch: mark with @pytest.mark.allow_dotenv to permit loading.
    """
    if request.node.get_closest_marker("allow_dotenv"):
        return
    # If dotenv is installed, replace load_dotenv with a no-op for this test.
    with suppress(Exception):
        monkeypatch.setattr(
            "dotenv.load_dotenv", lambda *_args, **_kwargs: False, raising=False
        )


@pytest.fixture(autouse=True)
def isolate_gemini_env(request, monkeypatch):
    """Ensure a clean GEMINI_* environment for each test.

    Escape hatches:
      - @pytest.mark.allow_env_pollution keeps current env unchanged
      - tests marked with @pytest.mark.api bypass isolation
    """
    if request.node.get_closest_marker("allow_env_pollution") or (
        "api" in request.node.keywords
    ):
        return

    for key in list(os.environ.keys()):
        if key.startswith("GEMINI_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("POLLUX_DEBUG_CONFIG", raising=False)


@pytest.fixture(autouse=True)
def neutral_home_config(request, monkeypatch, tmp_path):
    """Point home-config path to an isolated temp file by default."""
    if request.node.get_closest_marker("allow_real_home_config"):
        return

    fake_home_dir = tmp_path / "home_config_isolated"
    fake_home_dir.mkdir(parents=True, exist_ok=True)
    fake_home_file = fake_home_dir / "pollux.toml"
    monkeypatch.setenv("POLLUX_CONFIG_HOME", str(fake_home_file))


# --- Logging & Markers ---
@pytest.fixture(scope="session", autouse=True)
def quiet_noisy_libraries():
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def pytest_configure(config):
    """Configure custom markers for test organization."""
    markers = [
        "unit: Fast, isolated unit tests",
        "integration: Component integration tests with mocked APIs",
        "api: Real API integration tests (requires API key)",
        "characterization: Golden master tests to detect behavior changes.",
        "slow: Tests that take >1 second",
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)


def pytest_collection_modifyitems(items):
    """Automatically skip API tests when API key is unavailable."""
    if not (
        (os.getenv("POLLUX_API_KEY") or os.getenv("GEMINI_API_KEY"))
        and os.getenv("ENABLE_API_TESTS")
    ):
        skip_api = pytest.mark.skip(
            reason=(
                "API tests require POLLUX_API_KEY or GEMINI_API_KEY and ENABLE_API_TESTS=1"
            ),
        )
        for item in items:
            if "api" in item.keywords:
                item.add_marker(skip_api)
