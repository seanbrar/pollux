# Pollux Makefile

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
PYTEST = uv run pytest
PYTEST_ARGS = -v

# ------------------------------------------------------------------------------
# Main Commands
# ------------------------------------------------------------------------------
.PHONY: help install-dev lint format typecheck check test test-cov test-api docs-serve docs-build demo-data clean-demo-data clean hooks
.PHONY: mutmut

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install-dev: ## Install all development dependencies
	uv sync

hooks: ## Install pre-commit hooks
	@echo "Installing pre-commit hooks..."
	uv run pre-commit install

# ------------------------------------------------------------------------------
# Quality Checks
# ------------------------------------------------------------------------------

lint: ## Check formatting and lint code
	uv run ruff format --check .
	uv run ruff check .
	uv run rumdl check .

format: ## Format code and fix linting issues
	uv run ruff format .
	uv run ruff check --fix .
	uv run rumdl fmt .

typecheck: ## Static type checking with mypy
	uv run mypy .

check: lint typecheck test ## Run all checks (lint + typecheck + tests)

# ------------------------------------------------------------------------------
# Testing
# ------------------------------------------------------------------------------

test: ## Run all tests
	$(PYTEST) $(PYTEST_ARGS) -m "not api"

test-cov: ## Run tests with coverage (CI only)
	$(PYTEST) $(PYTEST_ARGS) -m "not api" --cov=src/pollux --cov-report=xml

test-api: .check-api-keys ## Run API tests (requires ENABLE_API_TESTS=1 + provider API key)
	ENABLE_API_TESTS=1 $(PYTEST) $(PYTEST_ARGS) -m "api"

# ------------------------------------------------------------------------------
# Mutation Testing (Local Only)
# ------------------------------------------------------------------------------

mutmut: ## Run mutation testing for src/pollux (slow; local only)
	uv run mutmut run

# ------------------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------------------

docs-build: ## Build the documentation site
	uv run mkdocs build

docs-serve: ## Serve docs locally at http://127.0.0.1:8000
	uv run mkdocs serve -a 127.0.0.1:8000

# ------------------------------------------------------------------------------
# Demo Data
# ------------------------------------------------------------------------------

TEXT ?= medium
MEDIA ?= basic

demo-data: ## Fetch demo data into cookbook/data/demo/
	uv run python scripts/demo_data.py --text "$(TEXT)" --media "$(MEDIA)"

clean-demo-data: ## Remove all demo data packs
	rm -rf cookbook/data/demo/text-medium cookbook/data/demo/text-full cookbook/data/demo/multimodal-basic cookbook/data/demo/.cache
	@if [ -d cookbook/data/demo ] && [ -z "$$(ls -A cookbook/data/demo 2>/dev/null)" ]; then rmdir cookbook/data/demo; fi || true

# ------------------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------------------

clean: ## Clean up all test and build artifacts
	rm -rf .pytest_cache/ coverage_html_report/ .coverage coverage.xml dist/ build/ *.egg-info site/
	find . -type d -name "__pycache__" -exec rm -rf {} +

# ------------------------------------------------------------------------------
# Internal Checks
# ------------------------------------------------------------------------------
.PHONY: .check-api-keys

.check-api-keys:
	@if [ -z "$$GEMINI_API_KEY" ] && [ -z "$$OPENAI_API_KEY" ]; then \
		echo "ERROR: no provider API key is set."; \
		echo "Set GEMINI_API_KEY and/or OPENAI_API_KEY, then rerun."; \
		exit 1; \
	fi
	@if [ -z "$$GEMINI_API_KEY" ]; then \
		echo "NOTE: GEMINI_API_KEY is not set; Gemini API tests will be skipped."; \
	fi
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo "NOTE: OPENAI_API_KEY is not set; OpenAI API tests will be skipped."; \
	fi
