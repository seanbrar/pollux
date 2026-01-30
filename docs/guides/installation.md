# Installation

Install Pollux quickly and choose a setup that matches your workflow.

## Requirements

- Python `3.13`
- macOS, Linux, or Windows (WSL recommended)

## Option A: PyPI (fastest)

```bash
pip install pollux
```

## Option B: GitHub Releases (stable wheel)

```bash
# 1) Download the latest .whl from:
# https://github.com/seanbrar/gemini-batch-prediction/releases/latest

# 2) Install the wheel (replace filename)
pip install ./pollux-*.whl

# Verify import
python -c "import pollux as p; print(p.__version__)"
```

## Option C: From source (contributors)

```bash
git clone https://github.com/seanbrar/gemini-batch-prediction.git
cd gemini-batch-prediction
pip install -e .
```

Optional visualization deps:

```bash
pip install "matplotlib~=3.10" "pandas~=2.3" "seaborn~=0.13"
```

Developer setup:

```bash
pip install -e .[dev]
make test
make lint
```

## Enable the real API (optional)

Mock mode is the default and needs no key. For real API calls:

=== "Bash/Zsh"

```bash
export GEMINI_API_KEY="<your key>"
export POLLUX_TIER=free      # free | tier_1 | tier_2 | tier_3
export POLLUX_USE_REAL_API=1
```

=== "PowerShell"

```powershell
$Env:GEMINI_API_KEY = "<your key>"
$Env:POLLUX_TIER = "free"
$Env:POLLUX_USE_REAL_API = "1"
```

!!! warning "Secrets & costs"
    Never commit keys. Real API usage may incur costs - set `POLLUX_TIER` to match
    your account.
