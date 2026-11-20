"""Create the package tiles from the same transparent artwork as the desktop app."""

import argparse
from pathlib import Path

from PIL import Image


def write_logos(icon: Path, destination: Path) -> None:
    with Image.open(icon) as source:
        for name, size in (("StoreLogo", 50), ("Square44x44Logo", 44), ("Square150x150Logo", 150)):
            logo = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            logo.save(destination / f"{name}.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("icon", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    write_logos(args.icon, args.destination)
