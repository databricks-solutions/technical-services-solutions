#!/usr/bin/env python3
"""Shrink screenshots in place: pngquant when it is installed, otherwise a 256-colour Pillow palette.

Run with uv so Pillow is available without installing it:
    uv run --with pillow python tools/screenshots/optimize.py docs/screenshots/*.png
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def shrink_with_pngquant(path: str) -> bool:
    exe = shutil.which("pngquant")
    if not exe:
        return False
    subprocess.run([exe, "--force", "--skip-if-larger", "--quality", "80-100", "--output", path, path],
                   check=False)
    return True


def shrink_with_pillow(path: str) -> None:
    from PIL import Image

    img = Image.open(path).convert("RGB")
    # Median cut keeps the pale UI tints (badges, table stripes) exact; fast octree shifts them to white.
    palette = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    tmp = path + ".tmp"
    palette.save(tmp, format="PNG", optimize=True)
    if os.path.getsize(tmp) < os.path.getsize(path):
        os.replace(tmp, path)
    else:
        os.remove(tmp)


def main(paths: list[str]) -> None:
    if not paths:
        sys.exit("usage: optimize.py FILE.png [FILE.png ...]")
    for path in paths:
        before = os.path.getsize(path)
        if not shrink_with_pngquant(path):
            shrink_with_pillow(path)
        after = os.path.getsize(path)
        print(f"{os.path.basename(path)}: {before / 1024:.0f} KB -> {after / 1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1:])
