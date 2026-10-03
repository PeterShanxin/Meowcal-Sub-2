from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_app_version", ROOT / "scripts/check_app_version.py"
)
assert SPEC and SPEC.loader
check_app_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_app_version)


def test_repository_versions_match() -> None:
    version = check_app_version.check_versions(check_app_version.manifest_versions(ROOT))
    assert check_app_version.VERSION.fullmatch(version)


@pytest.mark.parametrize(
    "path",
    [
        "src-tauri/Cargo.lock",
        "pyproject.toml",
        "src/meocosub2/overlay/ui/package-lock.json#root",
        "src/meocosub2/__init__.py",
    ],
)
def test_mismatched_manifest_fails(path: str) -> None:
    versions = check_app_version.manifest_versions(ROOT)
    versions[path] = "999.0.0"
    with pytest.raises(ValueError, match="disagree"):
        check_app_version.check_versions(versions)


def test_release_tag_must_match_version() -> None:
    versions = check_app_version.manifest_versions(ROOT)
    with pytest.raises(ValueError, match="Release tag must be"):
        check_app_version.check_versions(versions, "v999.0.0")


def test_invalid_version_fails() -> None:
    versions = check_app_version.manifest_versions(ROOT)
    versions["src-tauri/tauri.conf.json"] = "0.1"
    with pytest.raises(ValueError, match="major.minor.patch"):
        check_app_version.check_versions(versions)


@pytest.mark.parametrize(
    "source",
    ["", "__version__ = 2", '__version__ = "0.2.0"\n__version__ = "0.2.0"'],
)
def test_backend_requires_one_string_version(source: str, monkeypatch) -> None:
    read_text = Path.read_text

    def read(path: Path, *args, **kwargs) -> str:
        if path == ROOT / "src/meocosub2/__init__.py":
            return source
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="exactly one string __version__"):
        check_app_version.manifest_versions(ROOT)
