"""Suggest sticker sizes and positions for the board frames.

Usage:

    python widgets/stickers/suggest.py            # desktop board -> stickers[]
    python widgets/stickers/suggest.py narrow     # a variant -> variants.<name>.layout

Writes suggested size/x/y/rotate values back into config.json. Entries marked
"pinned": true are left untouched; the sticker marked "hero": true gets the
largest size share and is written last in draw order so it is never buried.

The layout is deterministic for a given frame and seed: an area budget is
split across the stickers (largest first, see HIERARCHY), positions start as
a seeded scatter and are relaxed until every pair of stickers overlaps by an
amount inside the OVERLAP band — enough to feel like a pile, never so much
that stickers swallow each other.
"""

import json
import math
import random
import sys
from pathlib import Path

from PIL import Image

WIDGET = Path(__file__).resolve().parent

AREA_FILL = 0.72                 # fraction of the frame covered by sticker boxes
OVERLAP_MIN, OVERLAP_MAX = 0.10, 0.30   # pairwise overlap band (1.0 = concentric)
TILT_MAX = 12                    # random tilt bounds, degrees
SIZE_MIN, SIZE_MAX = 0.16, 0.44  # sticker width bounds, fraction of frame width
HIERARCHY = [1.30, 1.00, 0.92, 0.84, 0.78, 0.72, 0.68, 0.65]  # size shares, largest first
GRAVITY = 0.001                  # pull toward frame centre per iteration;
                                 # weak — the scatter must keep filling the frame
ITERATIONS = 400


def load():
    return json.loads((WIDGET / "config.json").read_text(encoding="utf-8"))


def sticker_aspect(src):
    with Image.open(WIDGET / src) as im:
        w, h = im.size
    return w / h


def box_size(aspect, share, area_budget, frame_w, border):
    """On-canvas box (art + border + tilt allowance) width for one sticker."""
    box_w = math.sqrt(max(share * area_budget, 1) * aspect)
    box_w = min(max(box_w, SIZE_MIN * frame_w), SIZE_MAX * frame_w)
    size = (box_w - 2 * border) / 1.08          # 1.08 ≈ rotation expansion
    return max(10, round(size))


def relax(positions, radii, cw, ch, half):
    n = len(positions)
    cx, cy = cw / 2, ch / 2
    for _ in range(ITERATIONS):
        for i in range(n):
            for j in range(i + 1, n):
                dx = positions[j][0] - positions[i][0]
                dy = positions[j][1] - positions[i][1]
                dist = math.hypot(dx, dy) or 0.01
                rsum = radii[i] + radii[j]
                frac = max(0.0, 1 - dist / rsum)
                if frac > OVERLAP_MAX:
                    push = (frac - OVERLAP_MAX) * rsum * 0.5
                    positions[i][0] -= dx / dist * push * 0.5
                    positions[i][1] -= dy / dist * push * 0.5
                    positions[j][0] += dx / dist * push * 0.5
                    positions[j][1] += dy / dist * push * 0.5
                elif frac < OVERLAP_MIN and dist < 1.3 * rsum:
                    # only near-misses get pulled in: distant stickers are
                    # allowed to stay apart, a pile must not become a blob
                    pull = (OVERLAP_MIN - frac) * rsum * 0.25
                    positions[i][0] += dx / dist * pull * 0.5
                    positions[i][1] += dy / dist * pull * 0.5
                    positions[j][0] -= dx / dist * pull * 0.5
                    positions[j][1] -= dy / dist * pull * 0.5
        for i in range(n):
            positions[i][0] += (cx - positions[i][0]) * GRAVITY
            positions[i][1] += (cy - positions[i][1]) * GRAVITY
        for i, (hw, hh) in enumerate(half):
            positions[i][0] = min(max(positions[i][0], hw * 0.8), cw - hw * 0.8)
            positions[i][1] = min(max(positions[i][1], hh * 0.8), ch - hh * 0.8)


def auto_layout(sources, frame, opts, name, hero_src=None):
    """Geometry list for `sources` (hierarchy order) inside `frame`.

    Returns entries in draw order — the hero, if any, last so it is pasted
    on top. Deterministic for a given frame, seed and source list.
    """
    cw, ch = frame["width"], frame["height"]
    border = opts.get("border", 9)
    seed = opts.get("seed", 7)
    tilt = opts.get("tilt", TILT_MAX)
    rng = random.Random(f"suggest:{name}:{seed}:{cw}x{ch}")

    n = len(sources)
    if n == 0:
        return []

    # 1. area budget -> per-sticker box width. The hero takes the largest
    #    share; the rest keep their given order in the hierarchy.
    if hero_src in sources:
        order = [hero_src] + [s for s in sources if s != hero_src]
    else:
        order = list(sources)
    area_budget = AREA_FILL * cw * ch
    shares = (HIERARCHY * ((n // len(HIERARCHY)) + 1))[:n]
    total = sum(shares)
    shares = [x / total for x in shares]

    boxes, aspects = [], []
    for s, share in zip(order, shares):
        aspect = sticker_aspect(s)
        size = box_size(aspect, share, area_budget, cw, border)
        box_w = size * 1.08 + 2 * border
        boxes.append({"src": s, "size": size, "box_w": box_w, "box_h": box_w / aspect})
        aspects.append(aspect)

    radii = [(b["box_w"] + b["box_h"]) / 4 for b in boxes]
    half = [(b["box_w"] / 2, b["box_h"] / 2) for b in boxes]

    # 2. seeded scatter: hero at centre, the rest on a golden-angle ellipse
    #    that stretches with the frame — wide sheets spread wide, tall sheets
    #    spread tall, so the pile fills the frame instead of clustering
    rank = sorted(range(n), key=lambda i: -boxes[i]["box_w"])
    positions = [[0.0, 0.0] for _ in range(n)]
    golden = math.pi * (3 - math.sqrt(5))
    for r, i in enumerate(rank):
        if r == 0:
            positions[i] = [cw / 2, ch / 2]
        else:
            k = 0.45 + 0.10 * r
            a = r * golden + rng.uniform(-0.2, 0.2)
            positions[i] = [
                cw / 2 + cw / 2 * k * math.cos(a) * (1 + rng.uniform(-0.15, 0.15)),
                ch / 2 + ch / 2 * k * math.sin(a) * (1 + rng.uniform(-0.15, 0.15)),
            ]

    # 3. relax into the overlap band
    relax(positions, radii, cw, ch, half)

    # 4. the band pulls everything into a compact blob; stretch that blob to
    #    fill the frame, so a wide sheet spreads sideways and a tall one
    #    stacks up instead of floating centred in empty space
    xs = [p[0] + h[0] for p, h in zip(positions, half)] + \
         [p[0] - h[0] for p, h in zip(positions, half)]
    ys = [p[1] + h[1] for p, h in zip(positions, half)] + \
         [p[1] - h[1] for p, h in zip(positions, half)]
    cx, cy = cw / 2, ch / 2
    sx = max(1.0, min(cw * 0.92 / (max(xs) - min(xs) or 1), 2.4))
    sy = max(1.0, min(ch * 0.92 / (max(ys) - min(ys) or 1), 2.4))
    for i, p in enumerate(positions):
        p[0] = min(max(cx + (p[0] - cx) * sx, half[i][0] * 0.8), cw - half[i][0] * 0.8)
        p[1] = min(max(cy + (p[1] - cy) * sy, half[i][1] * 0.8), ch - half[i][1] * 0.8)

    # 5. draw order: non-hero stickers first, hero on top
    layout = []
    for i, b in enumerate(boxes):
        b["x"] = round(positions[i][0], 1)
        b["y"] = round(positions[i][1], 1)
        b["rotate"] = round(rng.uniform(-tilt, tilt), 1)
    hero_last = [b for b in boxes if b["src"] != hero_src] + \
                [b for b in boxes if b["src"] == hero_src]
    for b in hero_last:
        layout.append({
            "src": b["src"], "size": b["size"],
            "x": b["x"], "y": b["y"], "rotate": b["rotate"],
        })
    return layout


def report(name, frame, layout, opts):
    cw, ch = frame["width"], frame["height"]
    print(f"suggested {name} layout for {len(layout)} stickers in {cw}x{ch}")
    for e in layout:
        print(f"  {Path(e['src']).name:<16} size={e['size']:>3} at ({e['x']}, {e['y']}) rotate={e['rotate']}")
    print(f"  display box {cw}x{ch} — the build pads the PNG to exactly this aspect")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "wide"
    cfg = load()
    opts = {**cfg.get("defaults", {}), **cfg.get("suggest", {})}
    stickers = cfg["stickers"]
    sources = [s["src"] for s in stickers]
    hero = next((s["src"] for s in stickers if s.get("hero")), None)

    if name == "wide":
        frame = cfg.get("target") or cfg["canvas"]
        layout = auto_layout(sources, frame, opts, name, hero)
        by_src = {e["src"]: e for e in layout}
        # fill geometry in place, then put the hero last so it draws on top
        for s in stickers:
            if not s.get("pinned"):
                s.update({k: by_src[s["src"]][k] for k in ("size", "x", "y", "rotate")})
        hero_entry = next((s for s in stickers if s["src"] == hero), None)
        ordered = [s for s in stickers if s is not hero_entry]
        if hero_entry is not None:
            ordered.append(hero_entry)
        cfg["stickers"] = ordered
    else:
        variant = cfg.get("variants", {}).get(name)
        if variant is None:
            sys.exit(f"no variant named {name!r} in config.json")
        pinned = {e["src"]: e for e in variant.get("layout", []) if e.get("pinned")}
        layout = auto_layout(sources, variant, opts, name, hero)
        for e in layout:
            if e["src"] in pinned:
                e.update({k: pinned[e["src"]][k] for k in ("size", "x", "y", "rotate", "pinned")})
        variant["layout"] = layout
        frame = variant

    (WIDGET / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report(name, frame, layout, opts)


if __name__ == "__main__":
    main()
