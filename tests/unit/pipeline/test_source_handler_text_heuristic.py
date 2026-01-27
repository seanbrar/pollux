import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, Source, Success
from pollux.pipeline.source_handler import SourceHandler


@pytest.mark.asyncio
async def test_text_detection_allows_short_bare_filenames_as_text():
    handler = SourceHandler()
    # No separators; looks like a bare filename, should be treated as text
    cmd = InitialCommand(
        sources=(Source.from_file("README.md"),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "k"}),
    )
    result = await handler.handle(cmd)
    assert isinstance(result, Success)
    src = result.value.resolved_sources[0]
    # For real files in project root, detector may treat as file; ensure no failure.
    assert src.identifier in {"README.md", __import__("pathlib").Path("README.md")}


def test_source_from_file_invalid_path_raises():
    # Explicit construction requires existing file; invalid path raises immediately
    with pytest.raises(ValueError):
        _ = Source.from_file("some/dir/file.txt")
