# Pollux Batch Processing Testing Makefile

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
PYTEST = uv run pytest
PYTEST_ARGS = -v
COVERAGE_FAIL_UNDER ?= 80
COVERAGE_ARGS = --cov=pollux --cov-report=term-missing --cov-report=html:coverage_html_report --cov-report=xml --cov-fail-under=$(COVERAGE_FAIL_UNDER)
PR_COVERAGE_ARGS = --cov=pollux --cov-report=term-missing --cov-report=xml --cov-fail-under=$(COVERAGE_FAIL_UNDER)
PR_COVERAGE_ARGS_NO_FAIL = --cov=pollux --cov-report=term-missing --cov-report=xml


# Default log level for pytest's console output. Can be overridden.
TEST_LOG_LEVEL ?= WARNING

# Shared marker selection for fast, representative suites
FAST_MARKERS = "(contract or unit or characterization) and not slow and not api"

# PR coverage suite: include characterization to better reflect overall coverage
PR_COVERAGE_MARKERS = "(contract or unit or integration or workflows or security or characterization) and not slow and not api"

# ------------------------------------------------------------------------------
# Main Commands
# ------------------------------------------------------------------------------
.PHONY: help test test-all test-coverage install-dev clean docs-build docs-serve demo-data clean-demo-data typecheck lint lint-all test-pr-coverage test-pr-coverage-ci

help: ## ✨ Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install-dev: ## 📦 Install all development dependencies
	@echo "📦 Installing development dependencies..."
	uv sync --all-extras
	@echo "✅ Development environment ready"


docs-build: ## 📚 Build the documentation site
	@echo "📚 Building documentation..."

	uv run mkdocs build
	@echo "✅ Site built in site/"


docs-serve: ## 🚀 Serve docs locally at http://127.0.0.1:8000
	@echo "🚀 Serving documentation... (Ctrl+C to stop)"

	uv run mkdocs serve -a 127.0.0.1:8000


# ------------------------------------------------------------------------------
# Demo Data (repo-local, on-demand)
# ------------------------------------------------------------------------------

# TEXT pack: medium (default) or full
TEXT ?= medium
MEDIA ?= basic

demo-data: ## 📥 Fetch demo data into cookbook/data/demo/{text-medium|text-full} (+ optional media)
	@echo "📥 Preparing demo data packs: TEXT=$(TEXT) MEDIA=$(MEDIA)"
	uv run python scripts/demo_data.py --text "$(TEXT)" --media "$(MEDIA)"


clean-demo-data: ## 🧽 Remove all demo data packs
	@echo "🧽 Removing demo data under cookbook/data/demo/ ..."
	rm -rf cookbook/data/demo/text-medium cookbook/data/demo/text-full cookbook/data/demo/multimodal-basic cookbook/data/demo/.cache
	@if [ -d cookbook/data/demo ] && [ -z "$(shell ls -A cookbook/data/demo 2>/dev/null)" ]; then rmdir cookbook/data/demo; fi || true
	@echo "✅ Demo data cleaned"

test: ## 🎯 Run unit (+characterization when present) without coverage
	@echo "🎯 Running default test suite (unit + characterization when present)..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "unit or characterization"

test-coverage: ## 📊 Run all tests and generate a coverage report
	@echo "📊 Running all tests with coverage report..."
	$(PYTEST) $(PYTEST_ARGS) $(COVERAGE_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) tests/
	@echo "✅ Coverage report generated in coverage_html_report/"

test-pr-coverage: ## 🧮 PR coverage (XML only) on a representative fast suite
	@echo "🧮 Running PR coverage (XML only) on fast representative test set..."
	$(PYTEST) $(PYTEST_ARGS) $(PR_COVERAGE_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) \
		-m $(PR_COVERAGE_MARKERS)

# CI-friendly PR coverage: generate XML without failing on threshold
.PHONY: test-pr-coverage-ci
test-pr-coverage-ci: ## 🧮 PR coverage XML for CI (no threshold fail)
	@echo "🧮 Running PR coverage (no fail-under) for CI..."
	$(PYTEST) $(PYTEST_ARGS) $(PR_COVERAGE_ARGS_NO_FAIL) --log-cli-level=$(TEST_LOG_LEVEL) \
		-m $(PR_COVERAGE_MARKERS)

test-all: test test-integration test-workflows ## 🏁 Run all non-API tests
	@echo "✅ All non-API tests complete."

lint: ## ✒️ Check formatting and lint code
	@echo "✒️ Checking formatting and linting with ruff..."
	uv run ruff format --check .
	uv run ruff check .

format: ## ✨ Format code and fix linting issues
	@echo "✨ Formatting and fixing linting issues with ruff..."
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## 🔎 Static type checking with mypy (strict)
	@echo "🔎 Running mypy type checks (strict)..."
	uv run mypy .



lint-all: ## 🧹 Run ruff lint + mypy type checks
	@echo "🧹 Running full lint + typecheck..."
	$(MAKE) lint
	$(MAKE) typecheck

clean: ## 🧹 Clean up all test and build artifacts
	@echo "🧹 Cleaning up..."
	rm -rf .pytest_cache/ coverage_html_report/ .coverage coverage.xml dist/ build/ *.egg-info site/
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "✅ Cleanup completed"

# ------------------------------------------------------------------------------
# Optimized CI Test Targets
# ------------------------------------------------------------------------------
.PHONY: test-fast test-core test-dev test-progressive test-pr test-main test-fast-timed test-smoke

test-core: ## ⚡ Ultra-fast core tests (~15s): contracts + unit only
	@echo "⚡ Running core test suite..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "contract or unit"

test-fast: ## 🔧 Development suite (~30s): contract/unit/characterization (no slow/api)
	@echo "🔧 Running development test suite..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) \
		-m $(FAST_MARKERS)

test-dev: test-fast ## 🔧 Alias for test-fast (common development command)

test-smoke: ## 🚑 Ultra-fast critical checks (< 1m): a curated smoke subset
	@echo "🚑 Running smoke tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "smoke"

test-progressive: ## 📈 Progressive tests with fail-fast (contracts → unit → characterization)
	@echo "📈 Running progressive test suite with fail-fast..."
	@echo "  1️⃣ Architectural contracts..."
	@$(PYTEST) $(PYTEST_ARGS) -x --log-cli-level=$(TEST_LOG_LEVEL) -m "contract" || exit 1
	@echo "  2️⃣ Unit tests..."
	@$(PYTEST) $(PYTEST_ARGS) -x --log-cli-level=$(TEST_LOG_LEVEL) -m "unit" || exit 1
	@echo "  3️⃣ Characterization tests..."
	@$(PYTEST) $(PYTEST_ARGS) -x --log-cli-level=$(TEST_LOG_LEVEL) -m "characterization" || { ec=$$?; if [ $$ec -eq 5 ]; then echo "ℹ️  No characterization tests collected. Skipping step."; else exit $$ec; fi; }
	@echo "✅ Progressive test suite passed"

test-pr: test-progressive test-integration test-workflows ## 🔍 Pull Request suite (no slow tests)
	@echo "✅ Pull Request test suite complete"

test-main: test-all test-coverage ## 🎯 Main branch suite (everything + coverage)
	@echo "✅ Main branch test suite complete"

test-fast-timed: ## ⏱️ Development tests with timing information
	@echo "⏱️ Running development tests with timing..."
	@time $(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) \
		--durations=10 \
		-m $(FAST_MARKERS)

# ------------------------------------------------------------------------------
# Granular Test Targets
# ------------------------------------------------------------------------------
.PHONY: test-unit test-golden-files test-integration test-integration-light test-api test-workflows test-contracts test-slow

test-unit: ## 🧪 Run all unit tests
	@echo "🧪 Running unit tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "unit"

test-golden-files: ## 📸 Run characterization/golden file tests
	@echo "📸 Running characterization and golden file tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "characterization or golden_test"

test-integration: .check-semantic-release ## 🔗 Run integration tests (skips if semantic-release missing)
	@echo "🔗 Running integration tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "integration"

test-integration-light: ## 🔗 Integration tests without slow workflows
	@echo "🔗 Running lightweight integration tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "integration and not slow"

test-api: .check-api-key ## 🔑 Run API tests (requires GEMINI_API_KEY)
	@echo "🔑 Running API integration tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "api"

test-workflows: ## 🔧 Run workflow configuration tests
	@echo "🔧 Running workflow configuration tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "workflows"

# Contract-first testing
test-contracts: ## 🏛️ Run architectural contract tests (fast guards)
	@echo "🏛️ Running architectural contract tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "contract"

# Fast vs slow differentiation
test-slow: ## 🐌 Run slow tests only
	@echo "🐌 Running slow tests..."
	$(PYTEST) $(PYTEST_ARGS) --log-cli-level=$(TEST_LOG_LEVEL) -m "slow"

# ------------------------------------------------------------------------------
# Prerequisite Checks (Internal)
# ------------------------------------------------------------------------------
.PHONY: .check-api-key .check-semantic-release

.check-api-key:
	@if [ -z "$$GEMINI_API_KEY" ]; then \
		echo "❌ ERROR: GEMINI_API_KEY is not set."; \
		echo "   Get a key from https://ai.dev/ and export the variable."; \
		exit 1; \
	fi

.check-semantic-release:
	@if ! command -v semantic-release >/dev/null 2>&1; then \
		echo "⚠️ WARNING: semantic-release not found, skipping integration tests."; \
		echo "   Install with: pip install python-semantic-release"; \
		exit 0; \
	fi
