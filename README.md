# Pollux: Batch Prediction Framework

> **Google Summer of Code 2025 Project** — Efficient multimodal analysis via batching and context caching on Gemini.

**Mentoring org:** Google DeepMind (GSoC 2025)

![CI](https://github.com/seanbrar/gemini-batch-prediction/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/seanbrar/gemini-batch-prediction/graph/badge.svg)](https://codecov.io/gh/seanbrar/gemini-batch-prediction)
![Docs](https://img.shields.io/badge/docs-MkDocs-blue)
[![Docs Site](https://img.shields.io/badge/Docs-Site-2EA44F)](https://seanbrar.github.io/gemini-batch-prediction/)
![Python](https://img.shields.io/badge/Python-3.13+-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

Quick links:

- [Docs site](https://seanbrar.github.io/gemini-batch-prediction/)
- [Quickstart](https://seanbrar.github.io/gemini-batch-prediction/tutorials/quickstart/)
- [Cookbook (recipes)](https://seanbrar.github.io/gemini-batch-prediction/cookbook/)
- [API reference](https://seanbrar.github.io/gemini-batch-prediction/reference/api-reference/)
- [CLI (`pollux-config`)](https://seanbrar.github.io/gemini-batch-prediction/reference/cli/)
- [Installation](https://seanbrar.github.io/gemini-batch-prediction/how-to/installation/)
- [Troubleshooting](https://seanbrar.github.io/gemini-batch-prediction/how-to/troubleshooting/)

---

## 🎯 Project Overview

**Pollux** (formerly `gemini-batch`) delivers a **production-ready framework** for efficient multimodal analysis on Google's Gemini API. A modern **command pipeline** with intelligent batching and context caching yields **4–5x fewer API calls** and **up to 75% cost savings** while maintaining quality.

### Key Features

- **Command pipeline**: Modern async pipeline built for reliability and maintainability
- **Intelligent batching**: Automatic grouping/optimization of related API calls
- **Context caching**: Cut costs via Gemini’s context caching with safe fallbacks
- **Multimodal**: Unified interface for text, PDFs, images, videos, and YouTube URLs
- **Conversation memory**: Multi‑turn sessions with persistence and overflow handling
- **Production‑grade**: Strong tests, CI/CD, telemetry (opt‑in), and semantic releases

## ⚡ TL;DR

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "Summarize the key insights",
        source=types.Source.from_file("content.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

## ℹ️ Project Heritage

**Pollux** was originally developed as `gemini-batch` during Google Summer of Code 2025 with Google DeepMind. For the complete narrative and archived milestone roadmap, see [Project History & GSoC](https://seanbrar.github.io/gemini-batch-prediction/explanation/history/).

For forward‑looking plans, see the live [Project Roadmap](https://seanbrar.github.io/gemini-batch-prediction/roadmap/).

## 📦 Installation

### Releases (recommended)

Install the latest wheel from **[📥 Releases](https://github.com/seanbrar/gemini-batch-prediction/releases/latest)** for a stable build.

```bash
pip install ./pollux-*.whl

# Verify
python -c "import pollux as plx; print('✅', plx.__version__)"
```

Optional (for notebooks/visualization):

```bash
pip install "matplotlib~=3.10" "pandas~=2.3" "seaborn~=0.13"
```

### Development install (from source)

```bash
git clone https://github.com/seanbrar/gemini-batch-prediction.git
cd gemini-batch-prediction
pip install -e .
pip install "matplotlib~=3.10" "pandas~=2.3" "seaborn~=0.13"  # if using notebooks
```

<details>
<summary><b>👩‍💻 Developer Setup</b></summary>
<br>
If you want to contribute to the project or run tests, install the full development environment:

```bash
# Install development dependencies (includes testing, linting, etc.)
pip install -r dev-requirements.txt
# or
make install-dev

# Verify setup with tests
make test

# See all available development commands
make help
```

This project uses modern Python tooling including `ruff`, `mypy`, `pre-commit`, and `pytest` for a professional development experience.

</details>

### API Key Setup

Get your API key from [Google AI Studio](https://ai.dev/).

```bash
# Create a local .env from the template (git‑ignored)
cp .env.example .env
# Then edit .env and set values as needed
```

Example .env contents:

```dotenv
GEMINI_API_KEY=your_api_key_here                  # Provider key (fallback supported)
POLLUX_MODEL=gemini-2.0-flash                     # Library config
POLLUX_TIER=free                                  # free | tier_1 | tier_2 | tier_3
POLLUX_ENABLE_CACHING=true                        # Enable context caching
```

See the [comprehensive cookbook](cookbook/) and the online [Quickstart guide](https://seanbrar.github.io/gemini-batch-prediction/tutorials/quickstart/) for runnable examples.

Looking for more? Visit the [Docs site](https://seanbrar.github.io/gemini-batch-prediction/) (start at Tutorials → Quickstart).

### Rate Limit Configuration

**Important**: Gemini API rate limits vary substantially by billing tier. Configure your tier for optimal performance:

**Check your tier in Google AI Studio → Billing:**

- `free` - No billing enabled (default)
- `tier_1` - Billing enabled (most common paid tier)
- `tier_2`, `tier_3` - Higher volume plans

If no tier is configured, the library defaults to free tier limits. Use `pollux-config doctor` to confirm.

### One-Command Health Check

```bash
pollux-config doctor
# or inspect resolved config
pollux-config audit
```

### First Run Without an API Key

By default, the library runs in a deterministic mock mode (no external calls). This is ideal for validating your environment.

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "Say hello",
        source=types.Source.from_text("Hello content"),
    )
    print(result["status"], result["answers"][0])

asyncio.run(main())
```

Expected output (mocked): `ok echo: Say hello`

## 🔥 Quick Start

### Basic Usage

```python
import asyncio
from pollux import run_simple, types

async def main():
    # Simple single-source analysis
    result = await run_simple(
        "What are the main points and key insights?",
        source=types.Source.from_file("content.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

### Multi-Source Batch Processing

```python
import asyncio
from pollux import run_batch, types

async def main():
    sources = [
        types.Source.from_file("research_papers/paper1.pdf"),
        types.Source.from_url("https://youtube.com/watch?v=example"),
        types.Source.from_directory("data/")
    ]
    prompts = [
        "What are the main research themes?",
        "How do these sources complement each other?",
    ]

    envelope = await run_batch(prompts, sources=sources)
    for i, answer in enumerate(envelope["answers"], start=1):
        print(f"Q{i}: {answer}")

asyncio.run(main())
```

### Advanced Configuration

```python
from pollux import create_executor, types
from pollux.config import resolve_config

# Configure execution with custom options
config = resolve_config(overrides={
    "model": "gemini-2.0-flash",
    "tier": "tier_1",
    "enable_caching": True
})

executor = create_executor(config)

# Execute with specific options
result = await executor.execute(types.InitialCommand(
    prompt="Analyze this content for key insights",
    sources=[types.Source.from_file("analysis.pdf")],
    options=types.make_execution_options(
        result_prefer_json_array=True,
    )
))
```

## 📚 Documentation

### Core Resources

- **[📚 Cookbook](cookbook/)** - 25+ practical recipes organized by use case
  - 🚀 Getting Started (7 recipes)
  - 📚 Research Workflows (6 recipes)
  - ⚙️ Optimization (8 recipes)
  - 🏭 Production (5 recipes)
- **[🔬 Research Notebooks](notebooks/)** - Academic workflow demonstrations
- **[🧩 Extensions](src/pollux/extensions/)** - Official extension suite

Quickly list and run recipes with the runner:

```bash
python -m cookbook --list
python -m cookbook getting-started/analyze-single-paper.py -- --limit 1
```

## 🧭 Architecture At A Glance

- **`config/`**: Deterministic resolution across env, files, and overrides; includes `pollux-config` CLI.
- **`pipeline/`**: Async handler chain for source prep, planning, extraction, and result building.
- **`executor.py`**: Orchestrates the command pipeline, enforcing result invariants.
- **`telemetry.py`**: Opt‑in, ultra‑low‑overhead telemetry (`POLLUX_TELEMETRY=1`).

## 🤝 Contributing

This Google Summer of Code 2025 project is now complete! The framework is production-ready with comprehensive documentation and examples. Feedback and contributions are welcome! Please open an issue or reach out directly.

For technical implementation details, see the [development documentation](dev/).

## 📄 License

[MIT License](LICENSE) - This project is developed as part of Google Summer of Code 2025.
