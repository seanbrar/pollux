"""MinimalProjection: infallible fallback extractor used by ResultBuilder.

Provides a progressive degradation strategy (JSON -> numbered lists ->
newline splitting -> raw text) to produce a deterministic `ExtractionResult`
for any input. Intended for consumers who need a guaranteed, predictable
fallback when Tier 1 transforms do not match.
"""

import json
import re
from typing import Any, cast

from .extraction import ExtractionContext, ExtractionResult


class MinimalProjection:
    """Fallback extractor that always returns an `ExtractionResult`.

    Use this when a stable, non-raising extraction is required. The extractor
    applies several heuristics in order and guarantees a result matching
    `ctx.expected_count`.
    """

    def extract(self, raw: Any, ctx: ExtractionContext) -> ExtractionResult:
        """Extract answers from `raw` using progressive degradation.

        Args:
            raw: Raw API response to extract from.
            ctx: `ExtractionContext` with `expected_count` and optional schema.

        Returns:
            `ExtractionResult` with the final answers and a `method` tag.
        """
        text = self._to_text(raw)

        # Strategy 1: Try JSON array parsing
        if self._looks_like_json(text):
            json_result = self._try_parse_json_array(text)
            if json_result is not None:
                answers = self._normalize_and_pad(json_result, ctx.expected_count)
                return ExtractionResult(
                    answers=answers, method="minimal_json", confidence=0.8
                )

        # Strategy 2: Try numbered list extraction (for batch scenarios)
        if ctx.expected_count > 1:
            numbered = self._try_numbered_list(text)
            if (
                numbered and len(numbered) >= ctx.expected_count * 0.5
            ):  # At least half expected
                answers = self._pad_to_count(numbered, ctx.expected_count)
                return ExtractionResult(
                    answers=answers, method="minimal_numbered", confidence=0.6
                )

        # Strategy 3: Try newline splitting (simple text lists)
        if ctx.expected_count > 1 and "\n" in text:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                answers = self._pad_to_count(lines, ctx.expected_count)
                return ExtractionResult(
                    answers=answers, method="minimal_newlines", confidence=0.5
                )

        # Strategy 4: Ultimate fallback - always succeeds
        return self._ultimate_fallback(text, ctx.expected_count)

    def _to_text(self, raw: Any) -> str:
        """Convert any input to text safely.

        This method implements the robustness principle by handling
        any possible input type without failing.
        """
        if isinstance(raw, str):
            return raw

        if isinstance(raw, dict):
            # Try common text keys in order of likelihood
            for key in ("text", "content", "answer", "response", "message"):
                if key in raw and isinstance(raw[key], str):
                    return cast("str", raw[key])

            # Try nested provider structure (defensive navigation)
            try:
                candidates = raw.get("candidates", [])
                if isinstance(candidates, list) and candidates:
                    first_candidate = candidates[0]
                    if isinstance(first_candidate, dict):
                        content = first_candidate.get("content", {})
                        if isinstance(content, dict):
                            parts = content.get("parts", [])
                            if isinstance(parts, list) and parts:
                                first_part = parts[0]
                                if isinstance(first_part, dict):
                                    nested_text = first_part.get("text")
                                    if isinstance(nested_text, str):
                                        return nested_text
            except (AttributeError, KeyError, IndexError, TypeError):
                # Any navigation failure is handled gracefully
                pass

        # Handle objects with text attribute
        if hasattr(raw, "text") and isinstance(raw.text, str):
            return raw.text

        # Final fallback: string conversion
        try:
            return str(raw)
        except Exception:
            # Even str() can fail in pathological cases
            return "[unparseable content]"

    def _looks_like_json(self, text: str) -> bool:
        """Quick heuristic to check if text might contain JSON.

        This is a lightweight check to avoid expensive parsing attempts
        on clearly non-JSON content.
        """
        if not text:
            return False

        stripped = text.strip()

        # Direct JSON array indicators
        if stripped.startswith("[") and stripped.endswith("]"):
            return True

        # Markdown-wrapped JSON
        if "```json" in text.lower() or "```" in text:
            return True

        # JSON object that might contain arrays
        return bool(
            stripped.startswith("{") and ("[" in stripped or "answers" in text.lower())
        )

    def _try_parse_json_array(self, text: str) -> list[Any] | None:
        """Attempt to parse JSON array with multiple strategies.

        Returns None if parsing fails - never raises exceptions.
        This maintains the infallible guarantee.
        """
        # Strategy 1: Direct parsing
        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: Extract from markdown code blocks
        try:
            # Look for ```json blocks
            json_match = re.search(
                r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE
            )
            if json_match:
                json_text = json_match.group(1).strip()
                data = json.loads(json_text)
                if isinstance(data, list):
                    return data

            # Look for any ``` blocks that might contain JSON
            code_match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
            if code_match:
                code_text = code_match.group(1).strip()
                data = json.loads(code_text)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

        # Strategy 3: Extract array from JSON object
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict):
                # Look for array fields
                for key in ("answers", "results", "items", "data", "content"):
                    if key in data and isinstance(data[key], list):
                        return cast("list[Any]", data[key])
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    def _try_numbered_list(self, text: str) -> list[str] | None:
        """Extract numbered list items (1. item, 2. item, etc.).

        Returns None if no numbered list is found.
        """
        try:
            # Match numbered lists with various formats
            patterns = [
                r"^\s*(\d+)\.\s*(.+)$",  # 1. answer
                r"^\s*(\d+)\)\s*(.+)$",  # 1) answer
                r"^\s*\[(\d+)\]\s*(.+)$",  # [1] answer
            ]

            items = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                for pattern in patterns:
                    match = re.match(pattern, line)
                    if match:
                        number = int(match.group(1))
                        content = match.group(2).strip()
                        items.append((number, content))
                        break

            if not items:
                return None

            # Sort by number and extract content
            items.sort(key=lambda x: x[0])
            return [content for _, content in items]

        except (ValueError, AttributeError):
            return None

    def _normalize_and_pad(self, items: list[Any], count: int) -> list[str]:
        """Normalize items to strings and pad to expected count.

        This method implements the predictability principle by ensuring
        consistent output format regardless of input variations.
        """
        # Handle nested lists (flatten one level)
        if items and isinstance(items[0], list):
            # Flatten if we have a list of lists
            flattened = []
            for item in items:
                if isinstance(item, list):
                    flattened.extend(item)
                else:
                    flattened.append(item)
            items = flattened

        # Normalize all items to strings, handling nulls gracefully
        normalized = []
        for item in items:
            if item is None:
                normalized.append("")
            elif isinstance(item, str):
                normalized.append(item)
            else:
                # Convert any other type to string
                try:
                    normalized.append(str(item))
                except Exception:
                    normalized.append("")

        # Pad or truncate to expected count
        return self._pad_to_count(normalized, count)

    def _pad_to_count(self, items: list[str], count: int) -> list[str]:
        """Ensure exactly the expected number of items.

        This guarantees consistent output structure for the pipeline.
        """
        if len(items) >= count:
            return items[:count]

        # Pad with empty strings
        return items + [""] * (count - len(items))

    def _ultimate_fallback(self, text: str, count: int) -> ExtractionResult:
        """The final fallback that always succeeds.

        This method embodies the architectural guarantee that extraction
        never fails, no matter what input is provided.
        """
        # Normalize whitespace-only content to empty string
        normalized = text if text.strip() != "" else ""
        # Single/multiple answers case - put text in first position and pad rest when needed
        answers = [normalized] if count == 1 else [normalized] + [""] * (count - 1)

        return ExtractionResult(
            answers=answers,
            method="minimal_text",
            confidence=0.3,  # Low confidence but guaranteed success
        )
