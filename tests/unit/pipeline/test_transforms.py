"""Unit tests for Result Builder transforms.

Tests the Tier 1 transforms of the Two-Tier Transform Chain, verifying
their matching logic, extraction behavior, and adherence to the
architecture rubric's principles of simplicity and robustness.
"""

import pytest

from pollux.pipeline.results.transforms import (
    create_transform_registry,
    default_transforms,
    json_array_transform,
    markdown_list_transform,
    provider_normalized_transform,
    simple_text_transform,
)


class TestJsonArrayTransform:
    """Test JSON array transform matching and extraction."""

    def test_direct_json_array_matching(self):
        """Transform should match direct JSON arrays."""
        transform = json_array_transform()

        # Should match direct JSON arrays
        assert transform.matcher('["answer1", "answer2"]') is True
        assert transform.matcher("[1, 2, 3]") is True
        assert transform.matcher("[]") is True

        # Should not match non-arrays
        assert transform.matcher('{"key": "value"}') is False
        assert transform.matcher("simple text") is False

    def test_markdown_json_matching(self):
        """Transform should match markdown-wrapped JSON."""
        transform = json_array_transform()

        markdown_json = """```json
        ["answer1", "answer2", "answer3"]
        ```"""

        assert transform.matcher(markdown_json) is True

    def test_generic_code_block_matching(self):
        """Transform should match generic code blocks with JSON arrays."""
        transform = json_array_transform()

        code_block = """```
        ["answer1", "answer2"]
        ```"""

        assert transform.matcher(code_block) is True

    def test_direct_json_extraction(self):
        """Transform should extract from direct JSON arrays."""
        transform = json_array_transform()

        json_text = '["answer1", "answer2", "answer3"]'
        result = transform.extractor(json_text, {})

        assert result["answers"] == ["answer1", "answer2", "answer3"]
        assert result["confidence"] == 0.95
        assert result["structured_data"] == ["answer1", "answer2", "answer3"]

    def test_markdown_json_extraction(self):
        """Transform should extract from markdown-wrapped JSON."""
        transform = json_array_transform()

        markdown_json = """```json
        ["answer1", "answer2"]
        ```"""

        result = transform.extractor(markdown_json, {})

        assert result["answers"] == ["answer1", "answer2"]
        assert result["confidence"] == 0.95

    def test_generic_code_block_extraction(self):
        """Transform should extract from generic code blocks."""
        transform = json_array_transform()

        code_block = """```
        ["answer1", "answer2"]
        ```"""

        result = transform.extractor(code_block, {})

        assert result["answers"] == ["answer1", "answer2"]

    def test_null_value_normalization(self):
        """Transform should normalize null values to empty strings."""
        transform = json_array_transform()

        json_text = '["answer1", null, "answer3"]'
        result = transform.extractor(json_text, {})

        assert result["answers"] == ["answer1", "", "answer3"]

    def test_mixed_type_normalization(self):
        """Transform should normalize mixed types to strings."""
        transform = json_array_transform()

        json_text = '["string", 123, true, null]'
        result = transform.extractor(json_text, {})

        assert result["answers"] == ["string", "123", "True", ""]

    def test_invalid_json_raises_error(self):
        """Transform should raise ValueError for invalid JSON."""
        transform = json_array_transform()

        with pytest.raises(ValueError, match="Invalid JSON"):
            transform.extractor('["invalid json"', {})

    def test_non_array_json_raises_error(self):
        """Transform should raise ValueError for non-array JSON."""
        transform = json_array_transform()

        with pytest.raises(ValueError, match="Expected JSON array"):
            transform.extractor('{"key": "value"}', {})

    def test_dict_input_handling(self):
        """Transform should handle dict input by extracting text field."""
        transform = json_array_transform()

        dict_input = {"text": '["answer1", "answer2"]'}
        result = transform.extractor(dict_input, {})

        assert result["answers"] == ["answer1", "answer2"]


class TestProviderNormalizedTransform:
    """Test provider-normalized response structure transform."""

    def test_provider_structure_matching(self):
        """Transform should match provider SDK structures."""
        transform = provider_normalized_transform()

        provider_response = {
            "candidates": [{"content": {"parts": [{"text": "Response text"}]}}]
        }

        assert transform.matcher(provider_response) is True

    def test_non_provider_structure_rejection(self):
        """Transform should not match non-provider structures."""
        transform = provider_normalized_transform()

        # Various non-provider structures
        assert transform.matcher({"text": "simple"}) is False
        assert transform.matcher({"candidates": []}) is False
        assert transform.matcher("string input") is False
        assert transform.matcher([]) is False

    def test_provider_structure_extraction(self):
        """Transform should extract text from provider structure."""
        transform = provider_normalized_transform()

        provider_response = {
            "candidates": [
                {"content": {"parts": [{"text": "Extracted response text"}]}}
            ]
        }

        result = transform.extractor(provider_response, {})

        assert result["answers"] == ["Extracted response text"]
        assert result["confidence"] == 0.9

    def test_no_candidates_error(self):
        """Transform should raise error when no candidates present."""
        transform = provider_normalized_transform()

        with pytest.raises(ValueError, match="No candidates"):
            transform.extractor({"candidates": []}, {})

    def test_invalid_candidate_structure_error(self):
        """Transform should raise error for invalid candidate structure."""
        transform = provider_normalized_transform()

        with pytest.raises(ValueError, match="Invalid candidate structure"):
            transform.extractor({"candidates": ["not a dict"]}, {})

    def test_missing_content_error(self):
        """Transform should raise error when content is missing."""
        transform = provider_normalized_transform()

        invalid_response = {"candidates": [{"no_content": "here"}]}

        with pytest.raises(ValueError, match="Invalid content structure"):
            transform.extractor(invalid_response, {})

    def test_missing_parts_error(self):
        """Transform should raise error when parts are missing."""
        transform = provider_normalized_transform()

        invalid_response = {"candidates": [{"content": {"no_parts": "here"}}]}

        with pytest.raises(ValueError, match="No parts in content"):
            transform.extractor(invalid_response, {})

    def test_missing_text_error(self):
        """Transform should raise error when text is missing from parts."""
        transform = provider_normalized_transform()

        invalid_response = {
            "candidates": [{"content": {"parts": [{"no_text": "here"}]}}]
        }

        with pytest.raises(ValueError, match="No text found in part"):
            transform.extractor(invalid_response, {})


class TestSimpleTextTransform:
    """Test simple text transform for unstructured responses."""

    def test_simple_text_matching(self):
        """Transform should match plain text responses."""
        transform = simple_text_transform()

        # Should match simple text
        assert transform.matcher("Simple text response") is True
        assert transform.matcher("Multi word response") is True

        # Should not match structured formats
        assert transform.matcher('["json", "array"]') is False
        assert transform.matcher('{"json": "object"}') is False
        assert transform.matcher("```code block```") is False

    def test_empty_text_rejection(self):
        """Transform should not match empty or whitespace-only text."""
        transform = simple_text_transform()

        assert transform.matcher("") is False
        assert transform.matcher("   ") is False
        assert transform.matcher("\n\t") is False

    def test_structured_format_rejection(self):
        """Transform should not match text with structure markers."""
        transform = simple_text_transform()

        # Text containing structure markers should be rejected
        assert transform.matcher("Text with ```json in it") is False
        assert transform.matcher("Text mentioning JSON format") is False

    def test_simple_text_extraction(self):
        """Transform should extract and clean simple text."""
        transform = simple_text_transform()

        result = transform.extractor("Simple response text", {})

        assert result["answers"] == ["Simple response text"]
        assert result["confidence"] == 0.7

    def test_text_cleaning(self):
        """Transform should clean common prefixes from text."""
        transform = simple_text_transform()

        # Test various prefixes that should be removed
        test_cases = [
            ("Answer: The response", "The response"),
            ("The answer is: Response text", "Response text"),
            ("Based on the information, this is true", "this is true"),
        ]

        for input_text, expected in test_cases:
            result = transform.extractor(input_text, {})
            assert result["answers"][0] == expected

    def test_dict_input_text_extraction(self):
        """Transform should extract text from dict inputs."""
        transform = simple_text_transform()

        dict_input = {"text": "Extracted text content"}
        result = transform.extractor(dict_input, {})

        assert result["answers"] == ["Extracted text content"]


class TestMarkdownListTransform:
    """Test markdown list transform for structured lists."""

    def test_bullet_list_matching(self):
        """Transform should match bullet lists."""
        transform = markdown_list_transform()

        bullet_list = """
        - First item
        - Second item
        - Third item
        """

        assert transform.matcher(bullet_list) is True

    def test_numbered_list_matching(self):
        """Transform should match numbered lists."""
        transform = markdown_list_transform()

        numbered_list = """
        1. First item
        2. Second item
        3. Third item
        """

        assert transform.matcher(numbered_list) is True

    def test_mixed_list_indicators_matching(self):
        """Transform should match lists with mixed indicators."""
        transform = markdown_list_transform()

        mixed_list = """
        * First item with asterisk
        - Second item with dash
        + Third item with plus
        """

        assert transform.matcher(mixed_list) is True

    def test_insufficient_list_items_rejection(self):
        """Transform should not match text with too few list indicators."""
        transform = markdown_list_transform()

        single_item = "- Only one item"
        assert transform.matcher(single_item) is False

    def test_bullet_list_extraction(self):
        """Transform should extract items from bullet lists."""
        transform = markdown_list_transform()

        bullet_list = """
        - First answer
        - Second answer
        - Third answer
        """

        result = transform.extractor(bullet_list, {})

        assert result["answers"] == ["First answer", "Second answer", "Third answer"]
        assert result["confidence"] == 0.8

    def test_numbered_list_extraction(self):
        """Transform should extract items from numbered lists."""
        transform = markdown_list_transform()

        numbered_list = """
        1. First answer
        2. Second answer
        3. Third answer
        """

        result = transform.extractor(numbered_list, {})

        assert result["answers"] == ["First answer", "Second answer", "Third answer"]

    def test_various_numbered_formats(self):
        """Transform should handle various numbered list formats."""
        transform = markdown_list_transform()

        formats = [
            "[1] First answer\n[2] Second answer",
            "1) First answer\n2) Second answer",
            "1. First answer\n2. Second answer",
        ]

        for format_text in formats:
            result = transform.extractor(format_text, {})
            assert "First answer" in result["answers"]
            assert "Second answer" in result["answers"]

    def test_empty_list_error(self):
        """Transform should raise error when no list items found."""
        transform = markdown_list_transform()

        non_list_text = "This is not a list format"

        with pytest.raises(ValueError, match="No list items found"):
            transform.extractor(non_list_text, {})

    def test_mixed_list_markers(self):
        """Transform should handle mixed list markers in same text."""
        transform = markdown_list_transform()

        mixed_text = """
        - Bullet item
        1. Numbered item
        * Asterisk item
        """

        result = transform.extractor(mixed_text, {})

        assert "Bullet item" in result["answers"]
        assert "Numbered item" in result["answers"]
        assert "Asterisk item" in result["answers"]


class TestDefaultTransforms:
    """Test default transform collection and registry."""

    def test_default_transforms_collection(self):
        """Default transforms should return expected transforms."""
        transforms = default_transforms()

        # Should return a list of TransformSpec objects
        assert isinstance(transforms, list)
        assert len(transforms) > 0

        # All items should be TransformSpec instances
        for transform in transforms:
            assert hasattr(transform, "name")
            assert hasattr(transform, "matcher")
            assert hasattr(transform, "extractor")
            assert hasattr(transform, "priority")

    def test_transform_priority_ordering(self):
        """Default transforms should be ordered by priority."""
        transforms = default_transforms()

        # Extract priorities
        priorities = [t.priority for t in transforms]

        # Should be in descending order (highest priority first)
        assert priorities == sorted(priorities, reverse=True)

    def test_transform_registry_creation(self):
        """Transform registry should map names to transforms."""
        registry = create_transform_registry()

        # Should be a dict mapping names to TransformSpec objects
        assert isinstance(registry, dict)
        assert len(registry) > 0

        # All keys should be strings, all values should be TransformSpec
        for name, transform in registry.items():
            assert isinstance(name, str)
            assert hasattr(transform, "name")
            assert transform.name == name

    def test_expected_transform_names(self):
        """Registry should contain expected transform names."""
        registry = create_transform_registry()

        expected_names = [
            "json_array",
            "provider_normalized",
            "markdown_list",
            "simple_text",
        ]

        for expected_name in expected_names:
            assert expected_name in registry

    def test_transforms_are_callable(self):
        """All default transforms should have callable matcher/extractor."""
        transforms = default_transforms()

        for transform in transforms:
            # Matcher should be callable
            assert callable(transform.matcher)

            # Extractor should be callable
            assert callable(transform.extractor)

    def test_transform_names_are_unique(self):
        """All transform names should be unique."""
        transforms = default_transforms()
        names = [t.name for t in transforms]

        # No duplicates
        assert len(names) == len(set(names))

    def test_priority_values_are_reasonable(self):
        """Transform priorities should be in reasonable ranges."""
        transforms = default_transforms()

        for transform in transforms:
            # Priority should be non-negative integer
            assert isinstance(transform.priority, int)
            assert transform.priority >= 0

            # Priority should be in reasonable range (0-100)
            assert transform.priority <= 100
