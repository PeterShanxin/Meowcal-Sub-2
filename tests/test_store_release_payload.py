"""Verify the Store upload gate with synthetic package data and no credentials."""

import hashlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_store_release_payload import NAME, PUBLISHER, verify_payload  # noqa: E402

COMMIT = "a" * 40
STORE_VERSION = "1.0.2.0"
APP_VERSION = "0.4.2"
RELEASE_ID = 7


def fixture(directory: Path, *, arm_commit: str = COMMIT, publisher: str = PUBLISHER) -> Path:
    identity = f'Name="{NAME}" Publisher="{publisher}" Version="{STORE_VERSION}"'
    output = directory / f"MeowcalSub2-{STORE_VERSION}.msixbundle"
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(
            "AppxMetadata/AppxBundleManifest.xml",
            f"<Bundle><Identity {identity}/><Packages>"
            '<Package Architecture="x64" FileName="x64.msix"/>'
            '<Package Architecture="arm64" FileName="arm64.msix"/></Packages></Bundle>',
        )
        for arch, commit in (("x64", COMMIT), ("arm64", arm_commit)):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as package:
                package.writestr(
                    "AppxManifest.xml",
                    f'<Package><Identity {identity} ProcessorArchitecture="{arch}"/></Package>',
                )
                package.writestr(
                    "release.json",
                    json.dumps(
                        {
                            "architecture": arch,
                            "version": APP_VERSION,
                            "sourceCommit": commit,
                            "sourceDirty": False,
                            "distribution": "microsoft-store",
                        }
                    ),
                )
            bundle.writestr(f"{arch}.msix", data.getvalue())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (directory / "SHA256SUMS.txt").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    (directory / "release-provenance.json").write_text(
        json.dumps({"commit": COMMIT, "releaseId": RELEASE_ID, "appVersion": APP_VERSION}),
        encoding="utf-8",
    )
    return output


class TestStoreReleasePayload(unittest.TestCase):
    def test_wraps_only_the_verified_bundle(self):
        with TemporaryDirectory() as tmp:
            upload = Path(tmp) / "upload.zip"
            directory = Path(tmp) / "artifact"
            directory.mkdir()
            original = fixture(directory)
            self.assertEqual(
                verify_payload(directory, APP_VERSION, COMMIT, RELEASE_ID, STORE_VERSION, upload),
                STORE_VERSION,
            )
            with self.assertRaisesRegex(ValueError, "different GitHub release"):
                verify_payload(
                    directory, APP_VERSION, COMMIT, RELEASE_ID + 1, STORE_VERSION, upload
                )
            with zipfile.ZipFile(upload) as result:
                self.assertEqual(result.namelist(), [original.name])
                self.assertEqual(result.read(original.name), original.read_bytes())

    def test_rejects_wrong_publisher_and_wrong_embedded_commit(self):
        for changes, error in (
            ({"publisher": "wrong"}, "bundle identity"),
            ({"arm_commit": "b" * 40}, "package provenance"),
        ):
            with self.subTest(changes=changes), TemporaryDirectory() as tmp:
                upload = Path(tmp) / "upload.zip"
                fixture(Path(tmp), **changes)
                with self.assertRaisesRegex(ValueError, error):
                    verify_payload(
                        Path(tmp), APP_VERSION, COMMIT, RELEASE_ID, STORE_VERSION, upload
                    )
                self.assertFalse(upload.exists())

    def test_rejects_tampering_and_extra_files(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            package = fixture(directory)
            package.write_bytes(package.read_bytes() + b"tamper")
            upload = directory / "upload.zip"
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_payload(directory, APP_VERSION, COMMIT, RELEASE_ID, STORE_VERSION, upload)
            (directory / "extra.msix").touch()
            with self.assertRaisesRegex(ValueError, "Unexpected files"):
                verify_payload(directory, APP_VERSION, COMMIT, RELEASE_ID, STORE_VERSION, upload)


if __name__ == "__main__":
    unittest.main()
