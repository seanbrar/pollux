# Installation

Fast, reliable paths to install the library depending on your needs.

## Supported environment

- Python: `3.13` (required)
- Platforms: macOS, Linux, Windows (WSL recommended on Windows)

## Releases (recommended)

Install the latest wheel from GitHub Releases for stability.

```bash
# 1) Download the latest .whl from:
# https://github.com/seanbrar/gemini-batch-prediction/releases/latest

# 2) Install the wheel (replace filename as appropriate)
pip install ./pollux-*.whl

# Verify import
python -c "import pollux as gb; print(gb.__version__)"
```

Optional visualization deps (for Jupyter notebooks and plots):

```bash
pip install "matplotlib~=3.10" "pandas~=2.3" "seaborn~=0.13"
```

## From source (this repository)

Prefer this path if you plan to contribute or need latest `main`.

```bash
git clone https://github.com/seanbrar/gemini-batch-prediction.git
cd gemini-batch-prediction
pip install -e .

# Optional: notebooks/visualization helpers
pip install "matplotlib~=3.10" "pandas~=2.3" "seaborn~=0.13"
```

Developer setup (contributing/testing):

```bash
pip install -e .[dev]
make test
make lint
```

## Configure the environment

Mock mode (default) requires no API key. To use the real API:

=== "Bash/Zsh"

```bash
export GEMINI_API_KEY="<your key>"
export POLLUX_TIER=free      # free | tier_1 | tier_2 | tier_3
export POLLUX_USE_REAL_API=1

# Quick check (redacted diagnostics)
pollux-config doctor
```

=== "PowerShell"

```powershell
$Env:GEMINI_API_KEY = "<your key>"
$Env:POLLUX_TIER = "free"
$Env:POLLUX_USE_REAL_API = "1"
pollux-config doctor
```

!!! warning "Secrets & costs"
    Never commit keys. Use environment variables or a `.env` that is git‑ignored. Real API usage may incur costs—set `POLLUX_TIER` correctly for your account.

## Troubleshooting

- Module not found: ensure Python 3.13 and a clean virtual environment.
- Real API enabled but key missing: `pollux-config doctor` will flag it.
- Rate limit errors on first run: confirm `POLLUX_TIER` matches billing.

Last reviewed: 2025-09
