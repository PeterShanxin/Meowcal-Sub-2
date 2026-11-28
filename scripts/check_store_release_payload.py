"""Verify and wrap the Windows bundle before using Store credentials."""

import argparse
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryFile

from verify_store_bundle import SUPPORTED

NAME = "ShanxinLi.MeowcalSub2"
PUBLISHER = "CN=FCD37627-8F13-4157-933C-E729F9F08408"
VERSION = r"[1-9][0-9]*\.[0-9]+\.[0-9]+\.0"
MAX_PACKAGE_BYTES = 300_000_000
MAX_METADATA_BYTES = 64_000


def checked_entry(archive: zipfile.ZipFile, name: str, limit: int) -> zipfile.ZipInfo:
    matches = [entry for entry in archive.infolist() if entry.filename == name]
    if len(matches) != 1 or not 0 < matches[0].file_size < limit:
        raise ValueError(f"Invalid archive entry: {name}")
    return matches[0]


def metadata(archive: zipfile.ZipFile, name: str) -> bytes:
    return archive.read(checked_entry(archive, name, MAX_METADATA_BYTES))


def check_bundle(
    bundle: zipfile.ZipFile, app_version: str, commit: str, store_version: str
) -> None:
    identity = {"Name": NAME, "Publisher": PUBLISHER, "Version": store_version}
    manifest = ET.fromstring(metadata(bundle, "AppxMetadata/AppxBundleManifest.xml"))
    expected = manifest.find("{*}Identity")
    if expected is None or any(expected.get(key) != value for key, value in identity.items()):
        raise ValueError("Wrong Store bundle identity.")
    entries = manifest.findall("./{*}Packages/{*}Package")
    if (
        len(entries) != len(SUPPORTED)
        or {entry.get("Architecture") for entry in entries} != SUPPORTED
    ):
        raise ValueError("Wrong Store architectures.")
    for entry in entries:
        name, arch = entry.attrib["FileName"], entry.attrib["Architecture"]
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.msix", name):
            raise ValueError("Invalid bundle entry.")
        with (
            bundle.open(checked_entry(bundle, name, MAX_PACKAGE_BYTES)) as source,
            TemporaryFile() as nested,
        ):
            shutil.copyfileobj(source, nested)
            with zipfile.ZipFile(nested) as package:
                embedded = ET.fromstring(metadata(package, "AppxManifest.xml")).find("{*}Identity")
                if embedded is None or embedded.attrib != {
                    **identity,
                    "ProcessorArchitecture": arch,
                }:
                    raise ValueError("Wrong embedded package identity.")
                if json.loads(metadata(package, "release.json")) != {
                    "architecture": arch,
                    "version": app_version,
                    "sourceCommit": commit,
                    "sourceDirty": False,
                    "distribution": "microsoft-store",
                }:
                    raise ValueError("Wrong embedded package provenance.")


def verify_payload(
    artifact: Path,
    app_version: str,
    commit: str,
    release_id: int,
    store_version: str,
    upload: Path,
) -> str:
    """Read only exact named ZIP members; never extract the Actions artifact."""
    if not re.fullmatch(VERSION, store_version) or any(
        int(part) > 65535 for part in store_version.split(".")
    ):
        raise ValueError("Invalid Store package version.")
    if not 1000 < artifact.stat().st_size < MAX_PACKAGE_BYTES:
        raise ValueError("Unexpected Actions artifact size.")
    filename = f"MeowcalSub2-{store_version}.msixbundle"
    receipt = "SHA256SUMS.txt"
    provenance = "release-provenance.json"
    with zipfile.ZipFile(artifact) as transport, TemporaryFile() as bundle_file:
        if sorted(transport.namelist()) != sorted([filename, receipt, provenance]):
            raise ValueError("Unexpected files in the Store artifact.")
        line = metadata(transport, receipt).decode("utf-8-sig").strip()
        match = re.fullmatch(rf"([a-f0-9]{{64}})  {re.escape(filename)}", line)
        if not match:
            raise ValueError("Invalid bundle receipt.")
        if json.loads(metadata(transport, provenance)) != {
            "releaseId": release_id,
            "appVersion": app_version,
            "commit": commit,
        }:
            raise ValueError("Store artifact belongs to a different GitHub release.")
        with transport.open(checked_entry(transport, filename, MAX_PACKAGE_BYTES)) as source:
            shutil.copyfileobj(source, bundle_file)
        bundle_file.seek(0)
        if match[1] != hashlib.file_digest(bundle_file, "sha256").hexdigest():
            raise ValueError("Store artifact digest mismatch.")
        with zipfile.ZipFile(bundle_file) as bundle:
            check_bundle(bundle, app_version, commit, store_version)
        bundle_file.seek(0)
        with zipfile.ZipFile(upload, "x") as output, output.open(filename, "w") as destination:
            shutil.copyfileobj(bundle_file, destination)
    return store_version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("version")
    parser.add_argument("commit")
    parser.add_argument("release_id", type=int)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("upload", type=Path)
    args = parser.parse_args()
    template = ET.parse(args.manifest).find("{*}Identity")
    if template is None or template.get("Name") != NAME or template.get("Publisher") != PUBLISHER:
        raise ValueError("Wrong source manifest identity.")
    print(
        verify_payload(
            args.artifact,
            args.version,
            args.commit,
            args.release_id,
            template.attrib["Version"],
            args.upload,
        )
    )
