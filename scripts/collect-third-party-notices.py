"""Collect license evidence for the locked Windows shell and production studio."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "third-party-licenses"
LICENSE_NAME = re.compile(r"^(?:licen[cs]e|copying|unlicense)(?:[._-].*)?$", re.I)
NOTICE_NAME = re.compile(r"^(?:notice|copyright)(?:[._-].*)?$", re.I)


def command_json(arguments: list[str]) -> Any:
    result = subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=180)
    return json.loads(result.stdout)


@cache
def github_json(endpoint: str) -> Any:
    executable = shutil.which("gh")
    if not executable:
        raise RuntimeError("GitHub CLI is required for licenses omitted from published crates.")
    return command_json([executable, "api", endpoint])


def license_files(directory: Path, explicit: str | None = None) -> list[Path]:
    explicit_path = None
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and (LICENSE_NAME.match(path.name) or NOTICE_NAME.match(path.name))
    ]
    for path in directory.iterdir():
        if path.is_dir() and path.name.lower() in {"licenses", "licences"}:
            files.extend(child for child in path.rglob("*") if child.is_file())
    if explicit:
        path = Path(explicit)
        path = path if path.is_absolute() else directory / path
        if not path.is_file():
            raise RuntimeError(f"Declared license file is missing: {path}")
        files.append(path)
        explicit_path = path
    files = sorted(set(files))
    if not any(
        LICENSE_NAME.match(path.name)
        or any(
            part.lower() in {"licenses", "licences"} for part in path.relative_to(directory).parts
        )
        or path == explicit_path
        for path in files
    ):
        raise RuntimeError(f"No license text in {directory}")
    if any(not path.read_bytes().strip() for path in files):
        raise RuntimeError(f"Empty license evidence in {directory}")
    return files


def upstream_licenses(package: dict[str, Any], directory: Path) -> list[dict[str, Any]]:
    repository = re.match(r"https://github.com/([^/]+/[^/#]+)", package.get("repository") or "")
    if not repository:
        raise RuntimeError(f"No upstream repository for {package['name']} {package['version']}")
    repository_name = repository[1].removesuffix(".git")
    vcs_path = directory / ".cargo_vcs_info.json"
    vcs = json.loads(vcs_path.read_text()) if vcs_path.exists() else {}
    revision = vcs.get("git", {}).get("sha1")
    if not revision:
        tags = github_json(f"repos/{repository_name}/tags?per_page=100")
        tag = next(
            (tag for tag in tags if tag["name"] in {package["version"], "v" + package["version"]}),
            None,
        )
        if tag:
            revision = tag["commit"]["sha"]
    if package["name"] == "selectors" and package["version"] == "0.36.1":
        notice = re.split(rb"\r?\n\r?\n", (directory / "lib.rs").read_bytes(), maxsplit=1)[0]
        if (
            package["license"] != "MPL-2.0"
            or b"Mozilla Public" not in notice
            or b"License, v. 2.0" not in notice
        ):
            raise RuntimeError("selectors no longer contains its verified MPL-2.0 grant.")
        license_url = "https://www.mozilla.org/media/MPL/2.0/index.txt"
        with urlopen(license_url, timeout=30) as response:
            license_text = response.read()
        if not license_text.startswith(b"Mozilla Public License Version 2.0"):
            raise RuntimeError("Mozilla did not return the expected MPL-2.0 text.")
        return [
            {
                "name": "NOTICE",
                "data": notice + b"\n",
                "source": f"https://github.com/{repository_name}/blob/{revision}/selectors/lib.rs",
            },
            {"name": "LICENSE-MPL-2.0", "data": license_text, "source": license_url},
        ]
    if not revision:
        raise RuntimeError(
            f"No published commit or version tag for {package['name']} {package['version']}"
        )
    subdirectory = PurePosixPath(vcs.get("path_in_vcs") or "")
    ancestors = {str(path) for path in (subdirectory, *subdirectory.parents)}
    candidates = []
    for ancestor in sorted(ancestors):
        path = "" if ancestor == "." else "/" + quote(ancestor)
        entries = github_json(f"repos/{repository_name}/contents{path}?ref={revision}")
        for entry in entries:
            if entry["type"] == "file" and (
                LICENSE_NAME.match(entry["name"]) or NOTICE_NAME.match(entry["name"])
            ):
                candidates.append(entry)
            elif entry["type"] == "dir" and entry["name"].lower() in {"licenses", "licences"}:
                children = github_json(
                    f"repos/{repository_name}/contents/{quote(entry['path'])}?ref={revision}"
                )
                candidates.extend(child for child in children if child["type"] == "file")
    if not any(
        LICENSE_NAME.match(PurePosixPath(entry["path"]).name)
        or "/licenses/" in "/" + entry["path"].lower()
        for entry in candidates
    ):
        raise RuntimeError(f"No upstream license text: {repository_name}@{revision}")
    evidence = []
    for entry in candidates:
        blob = github_json(f"repos/{repository_name}/git/blobs/{entry['sha']}")
        evidence.append(
            {
                "name": entry["path"],
                "data": base64.b64decode(blob["content"]),
                "source": f"https://github.com/{repository_name}/blob/{revision}/{quote(entry['path'])}",
            }
        )
    return evidence


def rust_packages() -> list[dict[str, Any]]:
    executable = shutil.which("cargo")
    if not executable:
        raise RuntimeError("Cargo is required to resolve the locked Windows dependencies.")
    packages: dict[str, Any] = {}
    for target in ("x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"):
        metadata = command_json(
            [
                executable,
                "metadata",
                "--locked",
                "--offline",
                "--format-version",
                "1",
                "--filter-platform",
                target,
                "--manifest-path",
                str(ROOT / "src-tauri/Cargo.toml"),
            ]
        )
        packages.update(
            (package["id"], package) for package in metadata["packages"] if package.get("source")
        )
    return list(packages.values())


def npm_packages() -> list[dict[str, Any]]:
    studio = ROOT / "src/meocosub2/overlay/ui"
    lock = json.loads((studio / "package-lock.json").read_text())
    packages = []
    for relative, locked in lock["packages"].items():
        if not relative or locked.get("dev"):
            continue
        directory = studio / relative
        manifest = json.loads((directory / "package.json").read_text())
        if manifest["version"] != locked["version"]:
            raise RuntimeError(f"Installed npm version differs from lock: {relative}")
        packages.append(
            {
                "name": manifest["name"],
                "version": manifest["version"],
                "license": manifest.get("license"),
                "source": locked.get("resolved"),
                "repository": manifest.get("repository"),
                "directory": directory,
            }
        )
    return packages


def collect() -> None:
    records = []
    content = []
    for ecosystem, packages in (("rust", rust_packages()), ("npm", npm_packages())):
        for package in sorted(packages, key=lambda item: (item["name"], item["version"])):
            directory = (
                Path(package["manifest_path"]).parent
                if ecosystem == "rust"
                else package["directory"]
            )
            try:
                files = license_files(directory, package.get("license_file"))
            except RuntimeError:
                if ecosystem != "rust":
                    raise
                evidence = upstream_licenses(package, directory)
            else:
                evidence = [
                    {
                        "name": str(path.relative_to(directory)).replace("\\", "/"),
                        "data": path.read_bytes(),
                        "source": "published package " + path.name,
                    }
                    for path in files
                ]
            slug = re.sub(r"[^A-Za-z0-9._+-]", "_", package["name"] + "-" + package["version"])
            record = {
                "ecosystem": ecosystem,
                "name": package["name"],
                "version": package["version"],
                "source": package["source"],
                "repository": package.get("repository"),
                "declaredLicense": package.get("license"),
                "files": [],
            }
            for item in evidence:
                if not item["data"].strip():
                    raise RuntimeError(f"Empty license evidence: {package['name']} {item['name']}")
                relative = f"{ecosystem}/{slug}/{item['name']}"
                record["files"].append(
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(item["data"]).hexdigest(),
                        "source": item["source"],
                    }
                )
                content.append((relative, item["data"]))
            records.append(record)
    if OUTPUT.exists():
        if OUTPUT.resolve() != ROOT.resolve() / "output/third-party-licenses":
            raise RuntimeError("License output resolves outside its owned staging directory.")
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    for relative, data in content:
        destination = OUTPUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (OUTPUT / "index.json").write_text(
        json.dumps(
            {
                "scope": "Windows x64/ARM64 Rust resolve graph and production npm lock entries",
                "packages": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Third-party licenses",
        "",
        "This directory contains license texts for the locked Windows x64/ARM64 Rust",
        "dependency graphs (including build dependencies) and production studio npm packages.",
        "Python and Meowcal Core license evidence is distributed in their own directories.",
        "",
        "The declared license and source of each copied text are recorded in `index.json`.",
        "selectors 0.36.1 retains its published MPL-2.0 notice beside the license text",
        "from Mozilla, the license steward.",
        "",
        "| Package | Version | Declared license | License texts |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        links = ", ".join(
            f"[{Path(item['path']).name}]({quote(item['path'])})" for item in record["files"]
        )
        lines.append(
            f"| {record['ecosystem']}: {record['name']} | {record['version']} | {record['declaredLicense']} | {links} |"
        )
    (OUTPUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"Collected {len(records)} packages and {len(content)} license/notice files into {OUTPUT}"
    )


if __name__ == "__main__":
    try:
        collect()
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"License collection failed: {error}", file=sys.stderr)
        sys.exit(1)
