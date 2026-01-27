from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # typing-only
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from typing import Any


def _install_fake_google(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    # Create a fake google.genai module hierarchy and install into sys.modules
    fake_google = SimpleNamespace(genai=SimpleNamespace(Client=lambda **_: client))
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_google.genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_google.genai)


def _remove_fake_google() -> None:
    if "google" in sys.modules:
        del sys.modules["google"]
    if "google.genai" in sys.modules:
        del sys.modules["google.genai"]


def test_unsupported_provider_raises(tmp_path: Path) -> None:
    from pollux.extensions import provider_uploads as mod

    f = tmp_path / "x.txt"
    f.write_text("hi")
    with pytest.raises(NotImplementedError):
        mod.preupload_and_wait_active(f, provider="other")


def test_missing_api_key_raises_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    f = tmp_path / "x.txt"
    f.write_text("hi")
    # Ensure env missing
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Install a minimal fake module so import passes to env check
    class Files:
        def upload(self, **_: object) -> object:  # pragma: no cover - should not be hit
            return SimpleNamespace(name="files/1", uri=None)

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    with pytest.raises(mod.MissingCredentialsError):
        mod.preupload_and_wait_active(f)


def test_file_not_found_raises(tmp_path: Path) -> None:
    from pollux.extensions import provider_uploads as mod

    p = tmp_path / "missing.bin"
    with pytest.raises(FileNotFoundError):
        mod.upload_and_wait_active(p)


def test_upload_active_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    # Env present
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    f = tmp_path / "v.mp4"
    f.write_bytes(b"data")

    class Files:
        def __init__(self) -> None:
            self.calls = 0

        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/1", uri=None)

        def get(self, *, name: str) -> object:
            assert name == "files/1"
            self.calls += 1
            if self.calls >= 1:
                return SimpleNamespace(
                    name="files/1", uri="uri://files/1", state="ACTIVE"
                )
            return SimpleNamespace(name="files/1", uri=None, state="PROCESSING")

        def list(self) -> list[object]:  # pragma: no cover - not needed here
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    res = mod.upload_and_wait_active(f, timeout_s=5, poll_s=0)
    assert res.provider == "google"
    assert res.id == "files/1"
    assert res.uri == "uri://files/1"
    assert res.state == "ACTIVE"


def test_missing_dependency_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    # Ensure any fake module is gone and env key won't be consulted
    _remove_fake_google()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    f = tmp_path / "no_dep.bin"
    f.write_bytes(b"x")

    # Force import failure for google.genai by intercepting __import__
    import builtins as _builtins

    real_import = _builtins.__import__

    def raising_import(
        name: str,
        globs: Mapping[str, Any] | None = None,
        locs: Mapping[str, Any] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name.startswith("google.genai") or name == "google.genai":
            raise ImportError("no google.genai")
        if name == "google":
            # surface a bare google package without genai to ensure next import fails
            class _G:  # minimal stub
                pass

            return _G()
        # Delegate to the real import with the same call signature
        return real_import(name, globs, locs, fromlist, level)

    monkeypatch.setattr(_builtins, "__import__", raising_import)

    with pytest.raises(mod.MissingDependencyError):
        mod.upload_and_wait_active(f, timeout_s=0.01, poll_s=0)


def test_terminal_failure_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "z.bin"
    f.write_bytes(b"z")

    class Files:
        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/9")

        def get(self, *, name: str) -> object:
            assert name == "files/9"
            return SimpleNamespace(
                name="files/9", uri=None, state="FAILED", error={"message": "quota"}
            )

        def delete(self, *, name: str) -> None:  # pragma: no cover - verified via call
            assert name == "files/9"

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    with pytest.raises(mod.UploadFailedError):
        mod.upload_and_wait_active(f, timeout_s=5, poll_s=0)


def test_timeout_raises_inactive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "x.bin"
    f.write_bytes(b"x")

    class Files:
        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/1", uri=None)

        def get(self, *, name: str) -> object:
            assert name == "files/1"
            return SimpleNamespace(name="files/1", uri=None, state="PROCESSING")

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    # Make sleep a no-op for speed
    monkeypatch.setattr("time.sleep", lambda *_: None)
    # Use a very short timeout
    with pytest.raises(mod.UploadInactiveError):
        mod.upload_and_wait_active(f, timeout_s=0.01, poll_s=0)


def test_negative_poll_is_clamped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "w2.bin"
    f.write_bytes(b"w")

    class Files:
        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/4")

        def get(self, *, name: str) -> object:
            # never becomes ACTIVE to force a timeout
            assert name == "files/4"
            return SimpleNamespace(name="files/4", uri=None, state="PROCESSING")

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    delays: list[float] = []

    def capture_sleep(d: float) -> None:
        delays.append(d)

    monkeypatch.setattr("time.sleep", capture_sleep)

    with pytest.raises(mod.UploadInactiveError):
        mod.upload_and_wait_active(f, timeout_s=0.02, poll_s=-1.0, jitter_s=0.0)

    assert delays, "sleep should be called at least once"
    assert min(delays) >= 0.01


def test_state_normalization_with_enum_like(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "n.bin"
    f.write_bytes(b"n")

    class Files:
        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/enum")

        def get(self, *, name: str) -> object:
            assert name == "files/enum"

            class _Enum:
                name = "ACTIVE"

            return SimpleNamespace(
                name="files/enum", uri="uri://files/enum", state=_Enum()
            )

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    res = mod.upload_and_wait_active(f, timeout_s=5, poll_s=0)
    assert res.state == "ACTIVE"


def test_upload_returns_no_identifier_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "noid.bin"
    f.write_bytes(b"z")

    class Files:
        def upload(self, **_: object) -> object:
            # Missing both name and uri
            return SimpleNamespace()

        def get(self, *, _name: str) -> object:  # pragma: no cover - not reached
            raise AssertionError("should not be called")

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    with pytest.raises(RuntimeError):
        mod.upload_and_wait_active(f, timeout_s=5, poll_s=0)


def test_terminal_failure_cleans_up_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "failcleanup.bin"
    f.write_bytes(b"fc")

    class Files:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/fc")

        def get(self, *, name: str) -> object:
            assert name == "files/fc"
            return SimpleNamespace(name=name, state="FAILED", error={"message": "x"})

        def delete(self, *, name: str) -> None:
            self.deleted.append(name)

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    files = Files()
    client = SimpleNamespace(files=files)
    _install_fake_google(monkeypatch, client)

    with pytest.raises(mod.UploadFailedError):
        mod.upload_and_wait_active(f, timeout_s=0.01, poll_s=0, cleanup_on_timeout=True)

    assert files.deleted == ["files/fc"]


def test_list_fallback_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "y.bin"
    f.write_bytes(b"y")

    class Files:
        def upload(self, **_: object) -> object:
            # Upload returns uri-only id (no name)
            return SimpleNamespace(uri="uri://files/2")

        def get(self, *, _name: str) -> object:
            # Simulate API variant that requires list() to find the file
            raise RuntimeError("use list")

        def list(self) -> list[object]:
            return [SimpleNamespace(uri="uri://files/2", state="ACTIVE")]

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    res = mod.upload_and_wait_active(f, timeout_s=5, poll_s=0)
    assert res.id == "uri://files/2"
    assert res.uri == "uri://files/2"
    assert res.state == "ACTIVE"


def test_explicit_api_key_bypasses_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    # ensure env missing
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    f = tmp_path / "ae.bin"
    f.write_bytes(b"ae")

    class Files:
        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/5")

        def get(self, *, name: str) -> object:
            assert name == "files/5"
            return SimpleNamespace(name="files/5", uri="uri://files/5", state="ACTIVE")

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    res = mod.upload_and_wait_active(f, timeout_s=5, poll_s=0, api_key="explicit-key")
    assert res.id == "files/5"


def test_cleanup_on_timeout_calls_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "ct.bin"
    f.write_bytes(b"ct")

    class Files:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/7")

        def get(self, *, name: str) -> object:
            assert name == "files/7"
            return SimpleNamespace(name="files/7", uri=None, state="PROCESSING")

        def delete(self, *, name: str) -> None:
            self.deleted.append(name)

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    files = Files()
    client = SimpleNamespace(files=files)
    _install_fake_google(monkeypatch, client)

    monkeypatch.setattr("time.sleep", lambda *_: None)

    with pytest.raises(mod.UploadInactiveError):
        mod.upload_and_wait_active(f, timeout_s=0.01, poll_s=0, cleanup_on_timeout=True)

    assert files.deleted == ["files/7"]


def test_preupload_wrapper_returns_uri(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pollux.extensions import provider_uploads as mod

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "w.mp4"
    f.write_bytes(b"data")

    class Files:
        def upload(self, **_: object) -> object:
            return SimpleNamespace(name="files/3")

        def get(self, *, name: str) -> object:
            assert name == "files/3"
            return SimpleNamespace(name="files/3", uri="uri://files/3", state="ACTIVE")

        def list(self) -> list[object]:  # pragma: no cover - not used
            return []

    client = SimpleNamespace(files=Files())
    _install_fake_google(monkeypatch, client)

    uri = mod.preupload_and_wait_active(f, timeout_s=5, poll_s=0)
    assert uri == "uri://files/3"
