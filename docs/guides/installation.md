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
# https://github.com/seanbrar/pollux/releases/latest

# 2) Install the wheel (replace filename)
pip install ./pollux-*.whl

# Verify import
python -c "import pollux as p; print(p.__version__)"
```

## Option C: From source (contributors)

```bash
git clone https://github.com/seanbrar/pollux.git
cd pollux
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

For real API calls, set an API key:

=== "Bash/Zsh"

```bash
export GEMINI_API_KEY="<your key>"
export OPENAI_API_KEY="<your key>"
```

=== "PowerShell"

```powershell
$Env:GEMINI_API_KEY = "<your key>"
$Env:OPENAI_API_KEY = "<your key>"
```

!!! warning "Secrets & costs"
    Never commit keys. Real API usage may incur costs.
