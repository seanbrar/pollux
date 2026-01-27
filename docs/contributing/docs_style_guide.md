# Documentation Style Guide

Use this guide to write and maintain high‑quality documentation. It complements templates and checklists and applies to Tutorials, How‑To Guides, Explanations, and Reference.

## 1. Diátaxis Overview

Use the four documentation types intentionally:

- Tutorials: Guide newcomers through a concrete, end‑to‑end task with clear outcomes and prerequisites.
- How‑To Guides: Show concise, goal‑oriented steps; cross‑link to Reference and background when needed.
- Reference: Provide precise API details, docstring conventions (Google style), and generation hygiene.
- Explanation: Clarify concepts, trade‑offs, and design decisions, and connect them to practice.

## 2. Core Principles

1) Purpose first (Diátaxis): Every page declares its intent—teach (Tutorial), enable (How‑To), explain (Explanation), or specify (Reference).
2) User pathways: Link to at least one page in a different quadrant (“See also” or “Next steps”).
3) Small, complete units: Prefer many focused pages over omnibus pages.
4) Trustworthy examples: Code is minimal, typed, runnable, and copy‑pasteable.
5) Consistency over cleverness: Follow the voice and structure guidelines before inventing new patterns.

## 3. Anatomy of a Documentation Page

Use this skeleton for any page (adapt labels as needed):

1) H1 (Title): Task‑based (“Configure the Executor”), concept‑based (“Command Pipeline”), or feature‑based (“Executor API”).
2) Lead / Summary (2–3 sentences): What the page enables; avoid deep background.
3) Audience & Prerequisites: Who it’s for; what they must already know/have.
4) Body: Use clear H2/H3s. Keep sections short (3–8 paragraphs, 1–3 code blocks).
5) Outcomes / Results: What the reader can now do or has learned.
6) Links / Next steps: At least one cross‑quadrant link, plus lateral links within the section.
7) Last reviewed: Month/year (update when you touch the page).

Tip: The theme integrates the ToC into the sidebar; ensure headings (H2/H3) form a logical outline. Avoid single‑child hierarchies.

## 4. Quadrant‑Specific Guidance

### A) Tutorials (Learning‑oriented)

Use when guiding a newcomer through a concrete, end‑to‑end task.

Required sections

- What you’ll build (1 paragraph + screenshot if helpful)
- Prerequisites (explicit versions, access, data)
- Steps (numbered; each step ends with a visible result)
- Wrap‑up (what to try next)

Conventions

- Favor one path. Avoid branching and alternatives.
- Include time estimates only if reliable.
- Each step should have exactly one code block or command block where possible.

Example step pattern

```bash title="Install the release"
pip install ./pollux-*.whl
```

```python title="Initialize a client and run a minimal command"
from __future__ import annotations

def greet(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet("world"))
```

End with links to a How‑To that extends the project and an Explanation that provides background.

### B) How‑To Guides (Goal‑oriented)

Use when solving a specific problem. Assume some context exists.

Required sections

- Goal (“Configure logging to send JSON to stdout”)
- Applies to (versions/components)
- Steps (short, numbered)
- Verification (how to confirm success)
- Troubleshooting (1–3 known pitfalls)

Conventions

- Keep under 2–3 screens of content.
- Prefer one recipe per page; link out for alternatives.
- Include exact config snippets and a quick test.

```python title="Minimal example with type hints"
from __future__ import annotations
import logging

def configure_logger(level: int = logging.INFO) -> logging.Logger:
    """Create a JSON‑logging logger.

    Args:
        level: Logging level (e.g., logging.INFO).

    Returns:
        A configured logger instance.
    """
    logger = logging.getLogger("yourlib")
    logger.setLevel(level)
    return logger
```

Link to the relevant Reference (API) and an Explanation that motivates the setting.

### C) Reference (Information‑oriented)

Use for precise, exhaustive API descriptions.

Source of truth: Generated via mkdocstrings from Google‑style docstrings with type hints. Do not hand‑edit generated sections.

Docstring rules

- One‑line summary, then a blank line, then details.
- Use Args:, Returns:, Raises: (Google style).
- Reference types with typing names.
- Keep examples short; link to Tutorials/How‑Tos for longer ones.

```python
def add(a: int, b: int) -> int:
    """Return the sum of two integers.

    Args:
        a: The first addend.
        b: The second addend.

    Returns:
        The integer sum.
    """
    return a + b
```

API docs hygiene

- Private members (prefixed `_`) are excluded; keep internals private unless intentionally public.
- Write meaningful module/class docstrings—these become page intros.

Canonical API pages (avoid duplicates)

- Define each public API object in exactly one canonical page and use mkdocstrings only there (e.g., Core API under `reference/api/core.md`, Executor under `reference/api/executor.md`, Extensions under `reference/api/extensions/*`).
- In topical/reference pages (e.g., caching, configuration), link to the canonical API page instead of embedding another mkdocstrings block.
- Use stable, relative links to anchors generated by mkdocstrings, for example: `api/core.md#pollux.core.execution_options.ExecutionOptions`.
- When reorganizing APIs, move the mkdocstrings block to the new canonical page and update links; don’t leave duplicates.
- Our link checker (htmlproofer) ignores mkdocstrings anchors by pattern to prevent false 404s—don’t duplicate blocks to satisfy link checks.

### D) Explanation (Understanding‑oriented)

Use to clarify concepts, trade‑offs, and design decisions.

Patterns

- Start with a motivating question (“Why a command pipeline?”).
- Use diagrams sparingly; every figure needs a caption and is referenced in text.
- Keep opinions explicit and label them (“Design rationale”).
- Cross‑link to ADRs and to the concrete How‑To/Tutorials that put ideas into practice.

ADRs (Decisions)

- Each ADR includes Context → Decision → Consequences → Alternatives and a status (Proposed/Accepted/Superseded).
- Link forward/back between ADRs and the impacted APIs.

## 5. Interlinking Strategy (Cross‑Quadrant Web)

- Minimum links per page: 1 cross‑quadrant + 1 intra‑section.
- Placement:
  - Tutorials: end with “Next steps” (How‑To + Explanation).
  - How‑Tos: end with “Related reference” (specific API) and “Background” (concept).
  - Reference: add “Usage examples” (links to Tutorials/How‑Tos).
  - Explanations: add “Put it into practice” (How‑Tos/Tutorials).
- Anchor text: Descriptive, task‑based (“Configure the Executor”)—avoid “click here.”
- Avoid loops: Don’t trap readers in mutual links; always provide a forward step.

## 6. Headers and Footers

Global header (site‑wide)

- Product name, primary sections (Tutorials, How‑To guides, Reference, Explanation), Search.
- Keep the global header stable; do not add page‑specific CTAs here.

Page header (local)

- H1, short summary, status badges if relevant (Experimental/Stable).
- Optional breadcrumbs if useful.

Footer (page‑level)

- “Last reviewed” date and Edit this page (configured via `edit_uri`).
- “Found a problem?” → link to issue template.
- “Next steps” cross‑links (see Interlinking Strategy).

## 7. Use of Common MkDocs/Material Elements

Admonitions

- Use sparingly (≤1 per ~screenful). Choose the narrowest type:
  - `note` for context; `tip` for shortcuts;
  - `warning` for hazards (data loss, security);
  - `?+ note` for optional/advanced details (collapsible, via `pymdownx.details`).

Code blocks

- Prefer `python`, `bash`, or `yaml` fences.
- Titles and line numbers when helpful: ```python title="minimal.py" linenums="1"```
- Shell blocks omit the leading `$` to keep copy‑buttons useful.
- One action per block; show expected output in a separate `text` block.
- Prefer pure‑Python snippets that run as‑is and include type hints.

Tables

- Use for option matrices, not for long prose. Keep headers short and scannable.

Images & Figures

- Always provide alt text; add a caption under the image (italicized first line).
- Keep diagrams high‑contrast; do not rely on color alone for meaning.

Details & nesting

- Use `pymdownx.details` for collapsible advanced sections.
- Use `pymdownx.superfences` to nest code within admonitions (enabled).

## 8. Tone & Voice

- Plain, confident, encouraging. Prefer verbs (“Run”, “Configure”) over nouns (“Configuration”).
- Second person (“you”).
- Short sentences. Target ~20–25 words; break long sequences into lists.
- Consistent terminology. Use the glossary; capitalize “API”, “CLI”; prefer American English.

## 9. File/URL Conventions

- Filenames & slugs: `kebab-case.md`.
- One H1 per page; H2/H3 for structure.
- Images: store under `/assets/` or alongside the page in an `images/` folder; use relative links.

## 10. Authoring Checklist (pre‑PR)

- Page declares its quadrant and audience.
- Lead, prerequisites, outcomes present.
- At least one cross‑quadrant link and one intra‑section link.
- Code blocks typed, runnable, and minimal; no stray `$`.
- Admonitions used sparingly and correctly typed.
- “Last reviewed” set/updated; spellcheck passes.
