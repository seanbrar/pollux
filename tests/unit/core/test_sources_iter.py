from pathlib import Path

import pytest

from pollux.core.sources import iter_files, sources_from_directory

pytestmark = pytest.mark.unit


def _touch(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_iter_files_excludes_and_sorts(tmp_path):
    # Create structure with excluded directories and normal ones
    _touch(tmp_path / "b.txt", "b")
    _touch(tmp_path / "a.txt", "a")
    _touch(tmp_path / "dir" / "c.txt", "c")
    _touch(tmp_path / "node_modules" / "ignored.js", "n")
    _touch(tmp_path / ".git" / "ignored" / "file", "g")
    _touch(tmp_path / "__pycache__" / "ignored.pyc", "p")

    files = list(iter_files(tmp_path))
    # Should include only non-excluded files in sorted order
    rels = [f.relative_to(tmp_path).as_posix() for f in files]
    assert rels == ["a.txt", "b.txt", "dir/c.txt"]


def test_sources_from_directory_builds_file_sources(tmp_path):
    _touch(tmp_path / "d1" / "x.txt", "x")
    _touch(tmp_path / "d1" / "y.txt", "y")
    _touch(tmp_path / ".pytest_cache" / "z", "z")  # excluded

    sources = sources_from_directory(tmp_path / "d1")
    assert isinstance(sources, tuple)
    assert len(sources) == 2
    assert all(s.source_type == "file" for s in sources)
    paths = sorted(Path(str(s.identifier)).name for s in sources)
    assert paths == ["x.txt", "y.txt"]
