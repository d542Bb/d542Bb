"""Append a content-version query to the README's asset references so the
CDN serves fresh bytes after an image actually changes.

GitHub caches README images by URL: a changed PNG keeps serving the old
bytes for minutes after a push. Every generated image gets a short
pixel-content hash appended as ?v=... — rewritten only when the pixels
differ, so unchanged images never churn the README.

Usage: python widgets/bust_cache.py   (run after build_all.py)
"""

import hashlib
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def pixel_hash(path):
    """Hash the decoded pixels, not the encoded bytes: encoder version
    differences between machines would otherwise churn the README."""
    with Image.open(path) as im:
        return hashlib.sha1(im.convert("RGBA").tobytes()).hexdigest()[:6]


def main():
    assets = list((ROOT / "assets").glob("*.png")) + \
        list((ROOT / "assets").glob("*.gif"))
    hashes = {p.name: pixel_hash(p) for p in assets}
    names = "|".join(sorted((re.escape(n) for n in hashes), key=len, reverse=True))
    pattern = re.compile(rf"({names})(\?v=[0-9a-f]+)?")

    text = README.read_text(encoding="utf-8")
    changed = []

    def sub(m):
        name, query = m.group(1), m.group(2) or ""
        versioned = f"{name}?v={hashes[name]}"
        if versioned != m.group(0):
            changed.append(name)
        return versioned

    new_text = pattern.sub(sub, text)
    if new_text != text:
        README.write_text(new_text, encoding="utf-8")
    if changed:
        for name in sorted(set(changed)):
            print(f"busted {name} -> ?v={hashes[name]}")
    else:
        print("no image changes to bust")


if __name__ == "__main__":
    main()
