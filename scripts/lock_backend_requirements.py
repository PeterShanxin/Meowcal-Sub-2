"""Keep the release's hash-locked backend wheels in step with pyproject.toml.

config/backend-requirements.txt is what prepare-python-backend.ps1 installs, with
--require-hashes, into the embedded Python of both Windows packages. Each line pins
one distribution and lists the SHA-256 of the wheel every architecture installs.

  (default)   resolve the runtime dependencies with the current pins held, add
              missing dependencies, drop unused ones, and rewrite the file
  --upgrade-package NAME
              as the default, but release NAME's pin (repeatable); use after
              raising a floor in pyproject.toml or to take one fix
  --upgrade   resolve without holding pins, taking the newest allowed versions
  --check     fail unless the file already pins exactly what both architectures
              resolve, with every selected wheel's hash present

Resolution uses pip against the package index, with the same platform, Python
and ABI flags the release build uses, so it needs network access. pip evaluates
environment markers against the running interpreter rather than --platform, so
this runs on Windows and refuses dependencies selected by machine architecture.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config/backend-requirements.txt"
RUNTIME_LOCK = ROOT / "config/python-runtime.lock.json"
PLATFORMS = ("win_amd64", "win_arm64")
PIP_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    hashes: frozenset[str]


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(text: str) -> dict[str, Pin]:
    pins: dict[str, Pin] = {}
    for line in text.replace("\\\n", " ").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)((?:\s+--hash=sha256:[0-9a-f]{64})+)", line
        )
        if not match:
            raise ValueError(f"Not a hash-pinned requirement: {line}")
        name, version, hashes = match.groups()
        key = canonical(name)
        if key in pins:
            raise ValueError(f"Duplicate requirement: {name}")
        pins[key] = Pin(name, version, frozenset(re.findall(r"[0-9a-f]{64}", hashes)))
    return pins


def render_lock(pins: dict[str, Pin]) -> str:
    lines = []
    for key in sorted(pins):
        pin = pins[key]
        hashes = " ".join(f"--hash=sha256:{digest}" for digest in sorted(pin.hashes))
        lines.append(f"{pin.name}=={pin.version} {hashes}")
    return "\n".join(lines) + "\n"


def merge_platforms(resolutions: dict[str, dict[str, Pin]]) -> dict[str, Pin]:
    """One pin per distribution; architectures may select different wheels, not versions."""
    merged: dict[str, Pin] = {}
    for platform, pins in resolutions.items():
        for key, pin in pins.items():
            known = merged.get(key)
            if known is None:
                merged[key] = pin
            elif known.version != pin.version:
                raise ValueError(
                    f"{pin.name} resolves to {known.version} and {pin.version} ({platform})"
                )
            else:
                merged[key] = Pin(known.name, known.version, known.hashes | pin.hashes)
    return merged


def lock_problems(lock: dict[str, Pin], resolved: dict[str, Pin]) -> list[str]:
    """Hashes beyond the selected wheels are allowed: they still name exact artifacts."""
    problems = []
    for key in sorted(resolved.keys() - lock.keys()):
        problems.append(f"missing {resolved[key].name}=={resolved[key].version}")
    for key in sorted(lock.keys() - resolved.keys()):
        problems.append(f"unused {lock[key].name}=={lock[key].version}")
    for key in sorted(lock.keys() & resolved.keys()):
        pinned, wanted = lock[key], resolved[key]
        if pinned.version != wanted.version:
            problems.append(
                f"{pinned.name} is pinned at {pinned.version}, resolves to {wanted.version}"
            )
        elif not wanted.hashes <= pinned.hashes:
            problems.append(f"{pinned.name}=={pinned.version} lacks a selected wheel hash")
    return problems


def runtime_requirements() -> list[str]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]


def packaged_python() -> str:
    version = json.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))["version"]
    major, minor = version.split(".")[:2]
    return f"{major}.{minor}"


def resolve(platform: str, held: dict[str, Pin]) -> dict[str, Pin]:
    python = packaged_python()
    with tempfile.TemporaryDirectory() as scratch:
        constraints = Path(scratch, "constraints.txt")
        constraints.write_text(
            "".join(f"{pin.name}=={pin.version}\n" for pin in held.values()), encoding="utf-8"
        )
        report = Path(scratch, "report.json")
        # The flags mirror scripts/prepare-python-backend.ps1.
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                "--quiet", "--disable-pip-version-check", "--only-binary=:all:",
                "--platform", platform, "--python-version", python,
                "--implementation", "cp", "--abi", f"cp{python.replace('.', '')}",
                "--target", str(Path(scratch, "target")), "--report", str(report),
                "-c", str(constraints), *runtime_requirements(),
            ],
            check=True,
            timeout=PIP_TIMEOUT_SECONDS,
        )  # fmt: skip
        installs = json.loads(report.read_text(encoding="utf-8"))["install"]
    pins = {}
    for item in installs:
        metadata = item["metadata"]
        for requirement in metadata.get("requires_dist") or []:
            if "platform_machine" in requirement:
                raise ValueError(f"{metadata['name']} selects by architecture: {requirement}")
        digest = item["download_info"]["archive_info"]["hashes"]["sha256"]
        pins[canonical(metadata["name"])] = Pin(
            metadata["name"], metadata["version"], frozenset({digest})
        )
    return pins


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--upgrade", action="store_true")
    mode.add_argument("--upgrade-package", action="append", default=[], metavar="NAME")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("resolve on Windows; pip evaluates markers against this interpreter")

    lock = parse_lock(LOCK.read_text(encoding="utf-8"))
    released = {canonical(name) for name in args.upgrade_package}
    held = {} if args.upgrade else {k: pin for k, pin in lock.items() if k not in released}
    try:
        resolved = merge_platforms({platform: resolve(platform, held) for platform in PLATFORMS})
    except subprocess.CalledProcessError:
        # Usually a pyproject.toml floor now excludes a held pin.
        print(
            "Resolution failed with the current pins held (pip's reason is above). If"
            " pyproject.toml now excludes a pin, run: python"
            " scripts/lock_backend_requirements.py --upgrade-package NAME",
            file=sys.stderr,
        )
        return 1
    if args.check:
        problems = lock_problems(lock, resolved)
        for problem in problems:
            print(f"{LOCK.relative_to(ROOT).as_posix()}: {problem}", file=sys.stderr)
        if problems:
            print("Run: python scripts/lock_backend_requirements.py", file=sys.stderr)
        return 1 if problems else 0
    LOCK.write_text(render_lock(resolved), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
