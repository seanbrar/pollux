"""Core, always-on test fixtures and hooks.

Includes environment isolation, logging, marker registration, and common
utilities. Loaded as a pytest plugin from the root conftest.
"""

from __future__ import annotations

from contextlib import contextmanager, suppress
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


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


@pytest.fixture
def clean_env_patch():
    """Helper to apply a clean env baseline plus overrides as a context manager."""

    def _apply(extra: dict[str, str] | None = None) -> Generator[None]:
        base = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        if extra:
            base.update(extra)
        with patch.dict(os.environ, base, clear=True):
            yield

    return _apply


@pytest.fixture
def isolated_config_sources(tmp_path):
    """Completely isolate configuration sources for testing."""

    @contextmanager
    def _setup(
        *,
        pyproject_content: str = "",
        home_content: str = "",
        env_vars: dict[str, str] | None = None,
    ) -> Generator[None]:
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        if env_vars:
            for key, value in env_vars.items():
                if not key.startswith("GEMINI_"):
                    key = f"POLLUX_{key.upper()}"
                clean_env[key] = value

        project_dir = tmp_path / "project"
        project_dir.mkdir(exist_ok=True)
        pyproject_path = project_dir / "pyproject.toml"

        home_dir = tmp_path / "home"
        home_dir.mkdir(exist_ok=True)
        home_config_path = home_dir / "pollux.toml"

        if pyproject_content:
            pyproject_path.write_text(pyproject_content)
        if home_content:
            home_config_path.write_text(home_content)

        clean_env["POLLUX_PYPROJECT_PATH"] = str(pyproject_path)
        clean_env["POLLUX_CONFIG_HOME"] = str(home_config_path)

        with patch.dict(os.environ, clean_env, clear=True):
            yield

    return _setup


@pytest.fixture
def temp_toml_file():
    """Create temporary TOML files for testing as a context manager."""
    from contextlib import contextmanager
    import tempfile

    @contextmanager
    def _create(content: str) -> Generator[Path]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(content)
            f.flush()
            temp_path = Path(f.name)
        try:
            yield temp_path
        finally:
            if temp_path.exists():
                temp_path.unlink()

    return _create


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


# --- Common helpers ---
@pytest.fixture
def mock_api_key() -> str:
    return "test_api_key_12345_67890_abcdef_ghijkl"


@pytest.fixture
def mock_env(mock_api_key, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", mock_api_key)
    monkeypatch.setenv("POLLUX_MODEL", "gemini-2.0-flash")
    monkeypatch.setenv("POLLUX_ENABLE_CACHING", "False")


@pytest.fixture
def fs(fs):
    """pyfakefs helper that preserves OS-specific path separators."""
    fs.os = os
    return fs
