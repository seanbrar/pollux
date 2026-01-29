"""Root pytest configuration.

All fixtures are loaded via ``pytest_plugins`` from ``tests/fixtures/*`` to
avoid a monolithic conftest and keep a clear taxonomy across test types.
Tests should rely on fixture injection through pytest (not direct imports from
``tests/fixtures/*.py``), keeping usage consistent and discoverable.
"""

pytest_plugins = [
    "tests.fixtures.core",
]
