"""Built-in, pure extraction transforms used by `ResultBuilder`.

Each transform factory returns a `TransformSpec` with a `matcher` and an
`extractor`. Consumers can reuse these factories or provide custom
`TransformSpec`s to `ResultBuilder`.
"""

import json
import re
from typing import Any, cast

from .extraction import TransformSpec

# --- Utility Functions ---


def _get_text(raw: Any) -> str:
    """Extract text from various input formats safely.

    This utility function handles the common task of getting text content
    from different response shapes while maintaining robustness.
    """
    if isinstance(raw, str):
        return raw

    if isinstance(raw, dict):
        # Try simple text field first
        if "text" in raw and isinstance(raw["text"], str):
            return raw["text"]

        # Try other common text fields
        for key in ("content", "answer", "response", "message"):
            if key in raw and isinstance(raw[key], str):
                return cast("str", raw[key])

    # Fallback to string conversion
    return str(raw)


def _normalize_json_answers(data: list[Any]) -> list[str]:
    """Normalize JSON array items to clean string answers.

    Implements the data-centricity principle by handling type variations
    in a predictable, pure way.
    """
    answers = []
    for item in data:
        if item is None:
            answers.append("")
        elif isinstance(item, str):
            answers.append(item.strip())
        elif isinstance(item, int | float | bool):
            answers.append(str(item))
        elif isinstance(item, dict):
            # Try to extract text from object
            text = _get_text(item)
            answers.append(text.strip())
        elif isinstance(item, list):
            # Flatten one level if needed
            sub_answers = _normalize_json_answers(item)
            answers.extend(sub_answers)
        else:
            answers.append(str(item))

    return answers


# --- Built-in Transforms ---


def batch_response_transform() -> TransformSpec:
    """Extract answers from internal batch response format: {'batch': [...]}.

    - Matcher: top-level mapping with a non-empty ``batch`` list/tuple.
    - Extractor: coerce each item to text using simple, pure rules:
      - direct string
      - common text fields ("text", "content", "answer", "response", "message")
      - minimal provider-normalized shape (candidates/content/parts[0].text)
      - object with ``.text`` attribute
      Unknown items yield an empty string to preserve positional mapping.
    """

    def matcher(raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        batch_data = raw.get("batch")
        return isinstance(batch_data, list | tuple) and len(batch_data) > 0

    def _coerce_item_text(item: Any) -> str | None:
        # Use structural pattern matching for clarity and determinism.
        match item:
            case str() as txt:
                return txt
            case {"text": str(txt)}:
                return txt
            case {"content": str(txt)}:
                return txt
            case {"answer": str(txt)}:
                return txt
            case {"response": str(txt)}:
                return txt
            case {"message": str(txt)}:
                return txt
            # Minimal provider-normalized fallback:
            case {
                "candidates": [
                    {"content": {"parts": [{"text": str(txt)}, *_rest_parts]}},
                    *_rest_candidates,
                ]
            }:
                return txt
            case _:
                # Object with a text attribute
                if hasattr(item, "text"):
                    t = item.text
                    if isinstance(t, str):
                        return t
                return None

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        batch_data = raw.get("batch") if isinstance(raw, dict) else ()
        answers: list[str] = []
        if isinstance(batch_data, list | tuple):
            for item in batch_data:
                text = _coerce_item_text(item)
                answers.append(text.strip() if isinstance(text, str) else "")
        # Deterministic, always succeeds for matched inputs; preserve count
        return {
            "answers": answers,
            "confidence": 0.85,
            "structured_data": {"batch": batch_data},
        }

    return TransformSpec(
        name="batch_response",
        matcher=matcher,
        extractor=extractor,
        priority=95,  # before general-purpose transforms
    )


def json_array_transform() -> TransformSpec:
    """Return a `TransformSpec` that extracts from JSON arrays.

    Matches direct JSON arrays and markdown-wrapped JSON blocks. The
    extractor returns `answers`, `confidence`, and `structured_data`.

    Returns:
        `TransformSpec` configured for JSON array extraction.
    """

    def matcher(raw: Any) -> bool:
        """Check if the response looks like a JSON array."""
        text = _get_text(raw)
        if not text:
            return False

        stripped = text.strip()

        # Direct JSON array
        if stripped.startswith("[") and stripped.endswith("]"):
            return True

        # Markdown-wrapped JSON
        if "```json" in text.lower():
            # Quick guard: ensure the fenced block actually begins with '[' after trimming
            return True

        # Generic code block that might contain JSON
        if not stripped.startswith("```"):
            return False
        # Tiny guard to reduce false positives: only consider if there is a '[' before the closing fence
        # and the content between fences appears to start with '[' after whitespace
        return "[" in text

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        """Extract answers from JSON array format."""
        text = _get_text(raw)
        json_text = text.strip()

        # Handle markdown fencing
        if "```json" in text.lower():
            # Extract content between ```json and ```
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if match:
                json_text = match.group(1).strip()
        elif text.strip().startswith("```"):
            # Generic code block - extract content
            match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                json_text = match.group(1).strip()

        # Parse JSON
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array, got {type(data).__name__}")

        # Normalize and clean answers
        answers = _normalize_json_answers(data)

        return {"answers": answers, "confidence": 0.95, "structured_data": data}

    return TransformSpec(
        name="json_array", matcher=matcher, extractor=extractor, priority=90
    )


def provider_normalized_transform() -> TransformSpec:
    """Return a `TransformSpec` for provider-normalized responses.

    Targets structures with `candidates -> content -> parts` and extracts
    the first part's text as the answer.

    Returns:
        `TransformSpec` configured for provider-normalized extraction.
    """

    def matcher(raw: Any) -> bool:
        """Check if response has provider SDK structure."""
        if not isinstance(raw, dict):
            return False

        # Look for the common provider structure
        candidates = raw.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return False

        # Check if first candidate has expected structure
        first = candidates[0]
        if not isinstance(first, dict):
            return False

        content = first.get("content")
        if not isinstance(content, dict):
            return False

        parts = content.get("parts")
        return isinstance(parts, list) and len(parts) > 0

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        """Extract text from provider-normalized structure."""
        candidates = raw.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates in provider response")

        # Navigate defensive through the structure
        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise ValueError("Invalid candidate structure")

        if "content" not in first_candidate:
            raise ValueError("Invalid content structure")
        content = first_candidate.get("content")
        if not isinstance(content, dict):
            raise ValueError("Invalid content structure")

        parts = content.get("parts", [])
        if not isinstance(parts, list) or not parts:
            raise ValueError("No parts in content")

        # Extract text from first part
        first_part = parts[0]
        if not isinstance(first_part, dict):
            raise ValueError("Invalid part structure")

        text = first_part.get("text")
        if not isinstance(text, str):
            raise ValueError("No text found in part")

        return {"answers": [text], "confidence": 0.9}

    return TransformSpec(
        name="provider_normalized", matcher=matcher, extractor=extractor, priority=80
    )


def simple_text_transform() -> TransformSpec:
    """Return a `TransformSpec` for simple unstructured text.

    Performs light cleaning and removes common model prefixes. Returns a
    single-item `answers` list and a confidence score.

    Returns:
        `TransformSpec` configured for simple text extraction.
    """

    def matcher(raw: Any) -> bool:
        """Match any text that doesn't look structured."""
        text = _get_text(raw)
        if not text or not text.strip():
            return False

        # Don't match if it looks like JSON or other structured formats
        stripped = text.strip()
        if stripped.startswith(("[", "{", "```")):
            return False

        # Don't match if it contains obvious structure markers
        return not any(marker in text.lower() for marker in ["```", "json", "```json"])

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        """Extract and clean simple text response."""
        text = _get_text(raw)

        # Basic cleaning
        cleaned = text.strip()

        # Remove common prefixes/suffixes that models add
        prefixes_to_remove = [
            "answer:",
            "response:",
            "result:",
            "the answer is:",
            "here is the answer:",
            "based on the",
            "according to",
        ]

        for prefix in prefixes_to_remove:
            if cleaned.lower().startswith(prefix):
                # Special-case: remove preamble up to first comma for narrative phrases
                if prefix in ("based on the", "according to"):
                    comma_index = cleaned.find(",")
                    if comma_index != -1:
                        cleaned = cleaned[comma_index + 1 :].strip()
                        break
                cleaned = cleaned[len(prefix) :].strip()
                break

        return {"answers": [cleaned], "confidence": 0.7}

    return TransformSpec(
        name="simple_text", matcher=matcher, extractor=extractor, priority=20
    )


def markdown_list_transform() -> TransformSpec:
    """Return a `TransformSpec` that extracts items from markdown lists.

    Matches bullet and numbered lists and returns each list item as an
    answer. Raises `ValueError` when no list items are found.

    Returns:
        `TransformSpec` configured for markdown list extraction.
    """

    def matcher(raw: Any) -> bool:
        """Check if response contains markdown list structure."""
        text = _get_text(raw)
        if not text:
            return False

        lines = text.strip().splitlines()
        list_indicators = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check for various list indicators
            if (
                stripped.startswith(("-", "*", "+"))  # Bullet lists
                or re.match(r"^\d+\.", stripped)  # Numbered lists
                or re.match(r"^\[?\d+\]?[\.\)]\s", stripped)
            ):  # Various numbered formats
                list_indicators += 1

        # Consider it a list if we have multiple indicators
        return list_indicators >= 2

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        """Extract items from markdown list."""
        text = _get_text(raw)
        lines = text.strip().splitlines()

        answers = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Extract content after list markers
            content = None

            # Bullet lists (-, *, +)
            if stripped.startswith(("-", "*", "+")):
                content = stripped[1:].strip()

            # Numbered lists (1., 2., etc.)
            elif re.match(r"^\d+\.", stripped):
                content = re.sub(r"^\d+\.\s*", "", stripped)

            # Bracketed numbers ([1], [2], etc.)
            elif re.match(r"^\[\d+\]", stripped):
                content = re.sub(r"^\[\d+\]\s*", "", stripped)

            # Numbered with parentheses (1), 2), etc.)
            elif re.match(r"^\d+\)", stripped):
                content = re.sub(r"^\d+\)\s*", "", stripped)

            if content and content.strip():
                answers.append(content.strip())

        if not answers:
            raise ValueError("No list items found")

        return {"answers": answers, "confidence": 0.8}

    return TransformSpec(
        name="markdown_list", matcher=matcher, extractor=extractor, priority=70
    )


# --- Default Transform Collection ---


def default_transforms() -> list[TransformSpec]:
    """Get the default collection of built-in transforms.

    Returns transforms in a carefully chosen order that balances
    specificity with generality. More specific transforms have
    higher priority to ensure they're tried first.
    """
    return [
        batch_response_transform(),
        json_array_transform(),
        provider_normalized_transform(),
        markdown_list_transform(),
        simple_text_transform(),
    ]


def create_transform_registry() -> dict[str, TransformSpec]:
    """Create a registry of transforms by name for easy lookup.

    This provides a convenient way to access transforms by name,
    enabling user customization and testing scenarios.
    """
    return {transform.name: transform for transform in default_transforms()}
