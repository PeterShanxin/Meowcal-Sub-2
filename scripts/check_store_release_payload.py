"""Check the verified Windows bundle again before granting Store credentials."""

import argparse
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from verify_store_bundle import SUPPORTED

NAME = "ShanxinLi.MeowcalSub2"
PUBLISHER = "CN=FCD37627-8F13-4157-933C-E729F9F08408"
VERSION = r"[1-9][0-9]*\.[0-9]+\.[0-9]+\.0"


def verify_payload(
    directory: Path,
    app_version: str,
    commit: str,
    release_id: int,
    manifest_version: str,
    upload: Path,
) -> str:
    """Verify downloaded bytes and embedded identity, then create the API ZIP."""
    receipt = directory / "SHA256SUMS.txt"
    line = receipt.read_bytes().decode("utf-8-sig").strip()
    match = re.fullmatch(rf"([a-f0-9]{{64}})  (MeowcalSub2-({VERSION})\.msixbundle)", line)
    if not match:
        raise ValueError("Invalid bundle receipt.")
    digest, filename, store_version = match.groups()
    if store_version != manifest_version or any(
        int(part) > 65535 for part in store_version.split(".")
    ):
        raise ValueError("Invalid Store package version.")
    provenance = directory / "release-provenance.json"
    if {item.name for item in directory.iterdir()} != {filename, receipt.name, provenance.name}:
        raise ValueError("Unexpected files in the Store artifact.")
    if json.loads(provenance.read_bytes()) != {
        "releaseId": release_id,
        "appVersion": app_version,
        "commit": commit,
    }:
        raise ValueError("Store artifact belongs to a different GitHub release.")
    source = directory / filename
    if not 1000 < source.stat().st_size < 300_000_000:
        raise ValueError("Unexpected Store package size.")
    with source.open("rb") as stream:
        if digest != hashlib.file_digest(stream, "sha256").hexdigest():
            raise ValueError("Store artifact digest mismatch.")
    identity = {"Name": NAME, "Publisher": PUBLISHER, "Version": store_version}
    with zipfile.ZipFile(source) as bundle:
        manifest = ET.fromstring(bundle.read("AppxMetadata/AppxBundleManifest.xml"))
        expected = manifest.find("{*}Identity")
        if expected is None or any(expected.get(k) != v for k, v in identity.items()):
            raise ValueError("Wrong Store bundle identity.")
        entries = manifest.findall("./{*}Packages/{*}Package")
        if len(entries) != len(SUPPORTED) or {e.get("Architecture") for e in entries} != SUPPORTED:
            raise ValueError("Wrong Store architectures.")
        for entry in entries:
            name, arch = entry.attrib["FileName"], entry.attrib["Architecture"]
            if (
                not re.fullmatch(r"[A-Za-z0-9._-]+\.msix", name)
                or bundle.namelist().count(name) != 1
            ):
                raise ValueError("Invalid bundle entry.")
            with zipfile.ZipFile(io.BytesIO(bundle.read(name))) as package:
                embedded = ET.fromstring(package.read("AppxManifest.xml")).find("{*}Identity")
                if embedded is None or embedded.attrib != {
                    **identity,
                    "ProcessorArchitecture": arch,
                }:
                    raise ValueError("Wrong embedded package identity.")
                if json.loads(package.read("release.json").decode("utf-8-sig")) != {
                    "architecture": arch,
                    "version": app_version,
                    "sourceCommit": commit,
                    "sourceDirty": False,
                    "distribution": "microsoft-store",
                }:
                    raise ValueError("Wrong embedded package provenance.")
    with zipfile.ZipFile(upload, "x") as output:
        output.write(source, filename)
    return store_version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
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
            args.directory,
            args.version,
            args.commit,
            args.release_id,
            template.attrib["Version"],
            args.upload,
        )
    )
