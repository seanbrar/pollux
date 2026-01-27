# Conversation Extension: Getting Started

Goal: Build a minimal, real‑API conversation over a local file using the Conversation extension, then print answers and basic analytics.

!!! tip "See also (setup)"
    - Tutorials → Quickstart: tutorials/quickstart.md (first run, mock mode)
    - How‑to → Installation: how-to/installation.md (install paths)
    - How‑to → Verify Real API: how-to/verify-real-api.md (enable real calls)

We will use `cookbook/data/public/sample.txt` (Shakespeare’s Coriolanus) as our context source.

Prerequisites

- Python 3.13, repository cloned, `make install-dev` completed.
- A Gemini API key. Export environment variables as shown below.

Environment Setup (real API)

```bash
# bash/zsh
export GEMINI_API_KEY="<your key>"
export POLLUX_USE_REAL_API=1
export POLLUX_MODEL="gemini-2.0-flash"   # optional
export POLLUX_TIER="free"                # free | tier_1 | tier_2 | tier_3
```

Windows PowerShell

```powershell
$Env:GEMINI_API_KEY = "<your key>"
$Env:POLLUX_USE_REAL_API = "1"
$Env:POLLUX_MODEL = "gemini-2.0-flash"
$Env:POLLUX_TIER = "free"
```

## 1) Create an executor and a source

```python title="step1_setup.py"
from pollux import create_executor, types

# Create executor from env‑resolved config (real API if env set)
ex = create_executor()

# Use the Coriolanus sample file as context
src = types.Source.from_file("cookbook/data/public/sample.txt")
```

## 2) Start a conversation and ask one question

```python title="step2_single_turn.py"
import asyncio
from pollux.extensions import Conversation
from step1_setup import ex, src

async def main() -> None:
    conv = Conversation.start(ex, sources=[src])
    conv = await conv.ask(
        "Based only on the provided text file, summarize Shakespeare's 'Coriolanus' in 1–2 sentences."
    )
    print("Summary:\n", conv.state.turns[-1].assistant[:400])

asyncio.run(main())
```

Expected: a short summary string (real API content varies).

## 3) Add two sequential prompts (two turns)

```python title="step3_two_turns.py"
import asyncio
from pollux.extensions import Conversation, PromptSet
from step1_setup import ex, src

async def main() -> None:
    conv = Conversation.start(ex, sources=[src])
    conv, answers, metrics = await conv.run(
        PromptSet.sequential(
            "Based on the provided file, who is Caius Marcius Coriolanus?",
            "Name two other notable characters mentioned in the text (by name).",
        )
    )
    for i, a in enumerate(answers, start=1):
        print(f"\nQ{i} →\n{a[:400]}")

asyncio.run(main())
```

Expected: two printed answers.

## 4) Inspect quick analytics

```python title="step4_analytics.py"
import asyncio
from pollux.extensions import Conversation, PromptSet
from step1_setup import ex, src

async def main() -> None:
    conv = Conversation.start(ex, sources=[src])
    conv, answers, metrics = await conv.run(
        PromptSet.sequential("Q1?", "Q2?")
    )
    print("Analytics:", conv.analytics())

asyncio.run(main())
```

What You Should See

- A non‑empty summary for the first prompt.
- Two printed answers for the sequential prompts (content will vary by model version and prompt wording).
- A small analytics summary (turn counts and rough token metrics).

Validation Script (optional)

We include a tiny validator that runs the same flow and prints concise output:

```bash
python scripts/validate_conversation_tutorial.py
```

Expected shape (responses vary):

```text
--- Single: summary ---
<a short summary of Coriolanus>

--- Sequential: answers ---
Q1: Based on the provided file, who is Caius Marcius Coriolanus?
A1: <a short identification of Coriolanus>

Q2: Name two other notable characters mentioned in the text (by name).
A2: <two names from the play>

--- Analytics ---
turns=3 errors=0 est_tokens=... actual_tokens=...
```

Tips and Troubleshooting

- Ensure `POLLUX_USE_REAL_API=1` and `GEMINI_API_KEY` are set; otherwise you’ll run in mock mode.
- If throttled, set `POLLUX_TIER` to match your billing and reduce concurrency via config if needed.
- Response content can vary. For reproducible demos, use precise, grounded prompts and short outputs.

Next Steps

- See How‑to → Conversation: Advanced Features for policies, modes, and persistence.
- Explore Concepts → Conversation for the extension’s architecture and planning model.

Last reviewed: 2025‑09
