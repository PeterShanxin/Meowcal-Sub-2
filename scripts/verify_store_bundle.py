"""Check the actual embedded Store packages before giving a bundle to Partner Center."""

import argparse
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from check_windows_package import check_package

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {"x64", "arm64"}


def check_bundle(path: Path, commit: str) -> None:
    template = (ROOT / "store/AppxManifest.xml").read_text(encoding="utf-8")
    version = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text())["version"]
    with zipfile.ZipFile(path) as bundle, TemporaryDirectory() as tmp:
        manifest = ET.fromstring(bundle.read("AppxMetadata/AppxBundleManifest.xml"))
        expected = ET.fromstring(template).find("{*}Identity").attrib
        actual = manifest.find("{*}Identity").attrib
        if any(actual[k] != expected[k] for k in ("Name", "Publisher", "Version")):
            raise ValueError("Bundle identity differs from the Store reservation.")
        entries = manifest.findall("./{*}Packages/{*}Package")
        if len(entries) != 2 or {e.get("Architecture") for e in entries} != SUPPORTED:
            raise ValueError("Bundle must contain exactly one x64 package and one ARM64 package.")
        for entry in entries:
            arch = entry.attrib["Architecture"]
            name = entry.attrib["FileName"]
            if Path(name).name != name or not name.endswith(".msix"):
                raise ValueError("Unexpected embedded package filename.")
            with zipfile.ZipFile(bundle.extract(name, tmp)) as package:
                identity = ET.fromstring(package.read("AppxManifest.xml")).find("{*}Identity")
                if identity.attrib != {**expected, "ProcessorArchitecture": arch}:
                    raise ValueError(f"{arch} package identity differs from its manifest.")
                metadata = json.loads(package.read("release.json").decode("utf-8-sig"))
                if metadata != {
                    "architecture": arch,
                    "version": version,
                    "sourceCommit": commit,
                    "sourceDirty": False,
                    "distribution": "microsoft-store",
                }:
                    raise ValueError(f"{arch} package is from a different build.")
                dest = Path(tmp) / arch
                package.extractall(dest)
                check_package(dest, arch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    check_bundle(args.bundle, args.commit)
