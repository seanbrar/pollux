"""Behavioral tests for SourceHandler source resolution.

These tests verify that legacy file/url/text handling is preserved while
producing the new `Source` dataclass outputs expected by the pipeline.
"""

from pathlib import Path
import tempfile

import pytest

from pollux.config import resolve_config
from pollux.core.sources import sources_from_directory
from pollux.core.types import InitialCommand, Source, Success
from pollux.pipeline.source_handler import SourceHandler


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_text_content():
    handler = SourceHandler()
    text = "Hello world"
    source = Source.from_text(text)
    command = InitialCommand(
        sources=(source,),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "test"}),
    )

    result = await handler.handle(command)
    assert isinstance(result, Success)
    resolved = result.value
    assert len(resolved.resolved_sources) == 1
    src = resolved.resolved_sources[0]
    assert src.source_type == "text"
    assert src.identifier == text
    assert src.mime_type == "text/plain"
    assert src.content_loader() == text.encode()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_file_path_text_file():
    handler = SourceHandler()

    # Create a temporary text file for testing
    test_content = "This is a test file content.\nWith multiple lines."
    test_bytes = test_content.encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".txt", delete=False
    ) as temp_file:
        temp_file.write(test_bytes)
        temp_file_path = Path(temp_file.name)

    try:
        command = InitialCommand(
            sources=(Source.from_file(temp_file_path),),
            prompts=("p",),
            config=resolve_config(overrides={"api_key": "test"}),
        )
        result = await handler.handle(command)
        assert isinstance(result, Success)
        src = result.value.resolved_sources[0]
        assert src.source_type == "file"
        assert Path(src.identifier) == temp_file_path
        assert src.content_loader() == test_bytes
    finally:
        # Clean up the temporary file
        if temp_file_path.exists():
            temp_file_path.unlink()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_directory_expansion():
    handler = SourceHandler()

    # Create a temporary directory with test files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # Create multiple test files in the temporary directory
        test_files = [
            ("file1.txt", "Content of file 1"),
            ("file2.pdf", b"PDF content binary"),  # Simulate binary file
            ("file3.jpg", b"JPEG content"),  # Simulate image file
        ]

        for filename, content in test_files:
            file_path = temp_dir_path / filename
            if isinstance(content, str):
                file_path.write_text(content)
            elif isinstance(content, bytes):
                file_path.write_bytes(content)

        # Use helper to expand directory into Source objects
        dir_sources = sources_from_directory(temp_dir_path)
        command = InitialCommand(
            sources=dir_sources,
            prompts=("p",),
            config=resolve_config(overrides={"api_key": "test"}),
        )
        result = await handler.handle(command)
        assert isinstance(result, Success)
        sources = result.value.resolved_sources
        # Expect multiple sources from directory contents
        assert len(sources) == len(test_files)
        # All should be file sources
        assert all(s.source_type == "file" for s in sources)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_youtube_url():
    handler = SourceHandler()
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    command = InitialCommand(
        sources=(Source.from_youtube(url),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "test"}),
    )
    result = await handler.handle(command)
    assert isinstance(result, Success)
    src = result.value.resolved_sources[0]
    assert src.source_type == "youtube"
    assert src.identifier == url
    assert src.mime_type == "video/youtube"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_arxiv_pdf_url():
    handler = SourceHandler()
    url = "https://arxiv.org/pdf/1706.03762.pdf"
    command = InitialCommand(
        sources=(Source.from_arxiv(url),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "test"}),
    )
    result = await handler.handle(command)
    assert isinstance(result, Success)
    src = result.value.resolved_sources[0]
    assert src.source_type == "arxiv"
    assert src.identifier == url
    assert src.mime_type == "application/pdf"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_on_nonexistent_path(tmp_path: Path) -> None:
    # Create a path that definitely doesn't exist (cross-platform)
    missing = tmp_path / "definitely_does_not_exist_12345.xyz"

    # Source.from_file() should fail immediately for nonexistent files
    with pytest.raises(ValueError, match="path must point to an existing file"):
        Source.from_file(missing)
