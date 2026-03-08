"""Cookbook data-pack discovery, metadata loading, and installation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING, Any, Protocol, cast
import urllib.error
import urllib.request
import zipfile

if sys.version_info >= (3, 11):  # pragma: no branch - version-gated import
    import tomllib
else:  # pragma: no cover - Python 3.10 support
    import tomli as tomllib

if TYPE_CHECKING:
    from collections.abc import Sequence

    class HashLike(Protocol):
        """Minimal hashlib protocol used for generic checksum verification."""

        def update(self, data: bytes) -> object: ...

        def hexdigest(self) -> str: ...


DATA_REPO_URL = "https://github.com/seanbrar/pollux-cookbook-data"
DATA_REPO_ARCHIVE_URL = (
    "https://codeload.github.com/seanbrar/pollux-cookbook-data/zip/refs/heads/main"
)
ENV_DATA_DIR = "POLLUX_COOKBOOK_DATA_DIR"
ENV_DATA_SOURCE = "POLLUX_COOKBOOK_DATA_SOURCE"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COOKBOOK_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_SHARED_ROOT = _COOKBOOK_ROOT / "data" / "demo"


@dataclass(frozen=True, slots=True)
class PackSpec:
    """Identify one cookbook data pack."""

    namespace: str
    pack_id: str
    version: str = "1"

    @property
    def relative_root(self) -> Path:
        """Return the pack path relative to a data-repo root."""
        version_dir = f"v{self.version}"
        if self.namespace == "shared":
            return Path("shared") / version_dir
        return Path("projects") / self.pack_id / version_dir


SHARED_PACK = PackSpec(namespace="shared", pack_id="shared", version="1")


def cookbook_data_dir() -> Path:
    """Return the user-level install location for cookbook packs."""
    configured = os.getenv(ENV_DATA_DIR)
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "pollux" / "cookbook-data"
        )
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
        return base / "pollux" / "cookbook-data"
    xdg = os.getenv("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / "pollux" / "cookbook-data"


def install_hint(*, project: str | None = None) -> str:
    """Return the canonical install command for cookbook demo data."""
    if project:
        return f"just demo-data project={project}"
    return "just demo-data"


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _pack_root_from_candidate(path: Path, spec: PackSpec) -> Path | None:
    if (path / "pack.toml").is_file():
        return path
    candidate = path / spec.relative_root
    if (candidate / "pack.toml").is_file():
        return candidate
    return None


def _local_repo_candidates() -> list[Path]:
    configured = os.getenv(ENV_DATA_SOURCE)
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(_REPO_ROOT / "pollux-cookbook-data")
    return candidates


def find_pack_root(spec: PackSpec) -> Path | None:
    """Return the first available pack root across dev and installed locations."""
    for root in _local_repo_candidates():
        pack_root = _pack_root_from_candidate(root, spec)
        if pack_root is not None:
            return pack_root

    installed = _pack_root_from_candidate(cookbook_data_dir(), spec)
    if installed is not None:
        return installed
    return None


def load_pack_manifest(spec: PackSpec) -> dict[str, Any] | None:
    """Load ``pack.toml`` for the given pack when available."""
    pack_root = find_pack_root(spec)
    if pack_root is None:
        return None
    return _load_toml(pack_root / "pack.toml")


def pack_role_path(spec: PackSpec, role: str) -> Path | None:
    """Resolve one semantic asset role from a pack manifest."""
    pack_root = find_pack_root(spec)
    if pack_root is None:
        return None
    manifest = _load_toml(pack_root / "pack.toml")
    raw_roles = manifest.get("roles")
    if not isinstance(raw_roles, dict):
        return None
    relative = raw_roles.get(role)
    if not isinstance(relative, str):
        return None
    candidate = pack_root / relative
    return candidate if candidate.exists() else None


def default_shared_role_path(role: str) -> Path | None:
    """Resolve one shared-pack role, falling back to the legacy in-repo layout."""
    pack_path = pack_role_path(SHARED_PACK, role)
    if pack_path is not None:
        return pack_path

    legacy_map = {
        "text_dir": _LEGACY_SHARED_ROOT / "text-medium",
        "text_primary": _LEGACY_SHARED_ROOT / "text-medium" / "input.txt",
        "text_compare": _LEGACY_SHARED_ROOT / "text-medium" / "compare.txt",
        "media_dir": _LEGACY_SHARED_ROOT / "multimodal-basic",
        "media_paper": _LEGACY_SHARED_ROOT / "multimodal-basic" / "sample.pdf",
        "media_image": _LEGACY_SHARED_ROOT / "multimodal-basic" / "sample_image.jpg",
        "media_audio": _LEGACY_SHARED_ROOT / "multimodal-basic" / "sample_audio.mp3",
        "media_song": _LEGACY_SHARED_ROOT / "multimodal-basic" / "sample_song_64kb.mp3",
        "media_fridge_image": _LEGACY_SHARED_ROOT / "multimodal-basic" / "fridge.png",
        "media_video": _LEGACY_SHARED_ROOT / "multimodal-basic" / "sample_video.mp4",
    }
    candidate = legacy_map.get(role)
    if candidate is not None and candidate.exists():
        return candidate
    return None


def _open_url(url: str, timeout: float, user_agent: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    return urllib.request.urlopen(request, timeout=timeout)


def download_with_retries(
    sources: Sequence[str],
    dest: Path,
    *,
    timeout: float = 20.0,
    max_retries: int = 2,
) -> bool:
    """Download one file from candidate URLs with bounded retries."""
    user_agent = (
        "pollux-cookbook/1.0 (+https://github.com/seanbrar/pollux-cookbook-data) "
        f"python-urllib/{sys.version_info.major}.{sys.version_info.minor}"
    )
    temp_path = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)

    for url in sources:
        for _ in range(max_retries):
            try:
                with (
                    _open_url(url, timeout, user_agent) as response,
                    temp_path.open("wb") as handle,
                ):
                    shutil.copyfileobj(response, handle)
                temp_path.replace(dest)
                return True
            except (
                OSError,
                TimeoutError,
                urllib.error.HTTPError,
                urllib.error.URLError,
            ):
                if temp_path.exists():
                    temp_path.unlink()
    return False


def _fetch_pack_assets(pack_root: Path) -> list[str]:
    fetch_file = pack_root / "fetch.toml"
    if not fetch_file.exists():
        return []

    manifest = _load_toml(fetch_file)
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        return []

    failures: list[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        dest_value = asset.get("dest")
        urls_value = asset.get("urls")
        name_value = asset.get("name", "unnamed")
        checksum_value = asset.get("checksum")
        if not isinstance(dest_value, str) or not isinstance(urls_value, list):
            continue
        urls = [url for url in urls_value if isinstance(url, str)]
        if not urls:
            continue
        dest = pack_root / dest_value
        checksum = checksum_value if isinstance(checksum_value, str) else None
        if dest.exists() and dest.stat().st_size > 0:
            if checksum is None or verify_checksum(dest, checksum):
                continue
            dest.unlink()
        if download_with_retries(urls, dest) and (
            checksum is None or verify_checksum(dest, checksum)
        ):
            continue
        if dest.exists():
            dest.unlink()
        failures.append(str(name_value))
    return failures


def _build_hasher(checksum: str) -> tuple[HashLike, str]:
    """Return a hashlib hasher and normalized expected digest."""
    if ":" not in checksum:
        raise ValueError(
            f"Checksum must use the form '<algorithm>:<hex-digest>', got {checksum!r}."
        )
    algorithm, expected = checksum.split(":", 1)
    normalized_algorithm = algorithm.strip().lower()
    normalized_expected = expected.strip().lower()
    try:
        hasher = cast("HashLike", hashlib.new(normalized_algorithm))
    except ValueError as exc:  # pragma: no cover - depends on bad author input
        raise ValueError(
            f"Unsupported checksum algorithm {normalized_algorithm!r}."
        ) from exc
    if not normalized_expected:
        raise ValueError("Checksum digest cannot be empty.")
    return hasher, normalized_expected


def verify_checksum(path: Path, checksum: str) -> bool:
    """Verify one file against a generic checksum spec."""
    hasher, expected = _build_hasher(checksum)
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower() == expected


def _download_repo_snapshot(tmpdir: Path) -> Path:
    archive_path = tmpdir / "pollux-cookbook-data.zip"
    ok = download_with_retries([DATA_REPO_ARCHIVE_URL], archive_path)
    if not ok:
        raise RuntimeError(
            "Failed to download pollux-cookbook-data. "
            f"Download it manually from {DATA_REPO_URL} or set {ENV_DATA_SOURCE}."
        )
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(tmpdir)
    extracted = [path for path in tmpdir.iterdir() if path.is_dir()]
    if not extracted:
        raise RuntimeError(
            "Downloaded cookbook-data archive did not contain a directory."
        )
    return extracted[0]


def install_pack(
    spec: PackSpec,
    *,
    dest_base: Path | None = None,
    source_root: Path | None = None,
    fetch_assets: bool = True,
) -> tuple[Path, list[str]]:
    """Install or sync one pack into the user cookbook-data directory."""
    destination_root = (dest_base or cookbook_data_dir()) / spec.relative_root
    destination_root.parent.mkdir(parents=True, exist_ok=True)

    source_pack = _pack_root_from_candidate(source_root, spec) if source_root else None
    if source_pack is None:
        for candidate in _local_repo_candidates():
            source_pack = _pack_root_from_candidate(candidate, spec)
            if source_pack is not None:
                break

    with tempfile.TemporaryDirectory() as tmp:
        if source_pack is None:
            repo_root = _download_repo_snapshot(Path(tmp))
            source_pack = _pack_root_from_candidate(repo_root, spec)
        if source_pack is None:
            raise FileNotFoundError(
                f"Pack {spec.namespace}:{spec.pack_id}@v{spec.version} not found."
            )

        if destination_root.exists():
            shutil.rmtree(destination_root)
        shutil.copytree(source_pack, destination_root)

    failures = _fetch_pack_assets(destination_root) if fetch_assets else []
    return destination_root, failures


def remove_installed_data(*, dest_base: Path | None = None) -> Path:
    """Delete the installed cookbook-data directory if it exists."""
    base = dest_base or cookbook_data_dir()
    if base.exists():
        shutil.rmtree(base)
    return base


__all__ = [
    "DATA_REPO_URL",
    "ENV_DATA_DIR",
    "ENV_DATA_SOURCE",
    "SHARED_PACK",
    "PackSpec",
    "cookbook_data_dir",
    "default_shared_role_path",
    "find_pack_root",
    "install_hint",
    "install_pack",
    "load_pack_manifest",
    "pack_role_path",
    "remove_installed_data",
    "verify_checksum",
]
