set dotenv-load

# Show available recipes
default:
    @just --list

# Install all development dependencies
install-dev:
    uv sync

# Install pre-commit hooks
hooks:
    @echo "Installing pre-commit hooks..."
    uv run pre-commit install

# Check formatting and lint code
lint:
    uv run ruff format --check .
    uv run ruff check .
    uv run rumdl check .

# Format code and fix linting issues
format:
    uv run ruff format .
    uv run ruff check --fix .
    uv run rumdl fmt .

# Static type checking with mypy
typecheck:
    uv run mypy .

# Run all checks (lint + typecheck + tests)
check: lint typecheck test

# Run all tests
test:
    uv run pytest -v -m "not api"

# Run tests with coverage (CI only)
test-cov:
    uv run pytest -v -m "not api" --cov=src/pollux --cov-report=xml

# Run API tests (requires ENABLE_API_TESTS=1 + provider API key)
test-api: _check-api-keys
    ENABLE_API_TESTS=1 uv run pytest -v -m "api"

# Run mutation testing for src/pollux (slow; local only)
mutmut:
    uv run mutmut run

# Build the documentation site
docs-build:
    uv run mkdocs build

# Serve docs locally at http://127.0.0.1:8000
docs-serve:
    uv run mkdocs serve -a 127.0.0.1:8000

# Fetch demo data into cookbook/data/demo/
demo-data text="medium" media="basic":
    uv run python scripts/demo_data.py --text "{{ text }}" --media "{{ media }}"

# Remove all demo data packs
clean-demo-data:
    rm -rf cookbook/data/demo/text-medium cookbook/data/demo/text-full cookbook/data/demo/multimodal-basic cookbook/data/demo/.cache
    @if [ -d cookbook/data/demo ] && [ -z "$$(ls -A cookbook/data/demo 2>/dev/null)" ]; then rmdir cookbook/data/demo; fi || true

# Clean up all test and build artifacts
clean:
    rm -rf .pytest_cache/ coverage_html_report/ .coverage coverage.xml dist/ build/ *.egg-info site/
    find . -type d -name "__pycache__" -exec rm -rf {} +

# Private recipe used by test-api to ensure API keys exist
[private]
_check-api-keys:
    #!/usr/bin/env bash
    if [ -z "$GEMINI_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then \
        echo "ERROR: no provider API key is set."; \
        echo "Set GEMINI_API_KEY, OPENAI_API_KEY, and/or ANTHROPIC_API_KEY, then rerun."; \
        exit 1; \
    fi
    if [ -z "$GEMINI_API_KEY" ]; then \
        echo "NOTE: GEMINI_API_KEY is not set; Gemini API tests will be skipped."; \
    fi
    if [ -z "$OPENAI_API_KEY" ]; then \
        echo "NOTE: OPENAI_API_KEY is not set; OpenAI API tests will be skipped."; \
    fi
    if [ -z "$ANTHROPIC_API_KEY" ]; then \
        echo "NOTE: ANTHROPIC_API_KEY is not set; Anthropic API tests will be skipped."; \
    fi
