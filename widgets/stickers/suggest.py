"""Suggest sticker sizes and positions for the board canvas.

Run after adding/removing stickers or changing the canvas size:

    python widgets/stickers/suggest.py

Writes suggested size/x/y/rotate values back into config.json (stickers
marked "pinned": true are left untouched), then rebuild the board to see
the result and fine-tune by hand if needed.

The layout is deterministic for a given seed: an area budget is split
across the stickers (largest first, see HIERARCHY), positions start as a
seeded scatter and are relaxed until every pair of stickers overlaps by
an amount inside the OVERLAP band — enough to feel like a pile, never
so much that stickers swallow each other.
"""

import json
import math
import random
from pathlib import Path

from PIL import Image

WIDGET = Path(__file__).resolve().parent
SCALE = 2

AREA_FILL = 0.62                 # fraction of the canvas covered by sticker boxes
OVERLAP_MIN, OVERLAP_MAX = 0.10, 0.30   # pairwise overlap band (1.0 = concentric)
TILT_MAX = 12                    # random tilt bounds, degrees
SIZE_MIN, SIZE_MAX = 0.16, 0.44  # sticker width bounds, fraction of canvas width
HIERARCHY = [1.30, 1.00, 0.92, 0.84, 0.78, 0.72, 0.68, 0.65]  # size shares, largest first
GRAVITY = 0.02                   # pull toward canvas centre per iteration
ITERATIONS = 400


def load():
    cfg = json.loads((WIDGET / "config.json").read_text(encoding="utf-8"))
    return cfg


def sticker_aspect(item):
    src = WIDGET / item["src"]
    with Image.open(src) as im:
        w, h = im.size
    return w / h


def box_size(item, share, area_budget, canvas_w, border):
    """On-canvas box (art + border + tilt allowance) width for one sticker."""
    aspect = sticker_aspect(item)
    box_w = math.sqrt(max(share * area_budget, 1) * aspect)
    box_w = min(max(box_w, SIZE_MIN * canvas_w), SIZE_MAX * canvas_w)
    size = (box_w - 2 * border) / 1.08          # 1.08 ≈ rotation expansion
    return max(10, round(size))


def relax(positions, radii, canvas_w, canvas_h, rng_state):
    n = len(positions)
    cx, cy = canvas_w / 2, canvas_h / 2
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
        for i, (hw, hh) in enumerate(rng_state["half"]):
            positions[i][0] = min(max(positions[i][0], hw * 0.8), canvas_w - hw * 0.8)
            positions[i][1] = min(max(positions[i][1], hh * 0.8), canvas_h - hh * 0.8)


def main():
    cfg = load()
    canvas = cfg["canvas"]
    cw, ch = canvas["width"], canvas["height"]
    opts = {**cfg.get("defaults", {}), **cfg.get("suggest", {})}
    border = opts.get("border", 9)
    seed = opts.get("seed", 7)
    tilt = opts.get("tilt", TILT_MAX)
    rng = random.Random(f"suggest:{seed}:{cw}x{ch}")

    stickers = [s for s in cfg["stickers"] if not s.get("pinned")]
    n = len(stickers)
    if n == 0:
        print("nothing to suggest")
        return

    # 1. area budget -> per-sticker box width (config order = size hierarchy:
    #    the first sticker gets the largest share, so put your hero first)
    area_budget = AREA_FILL * cw * ch
    shares = (HIERARCHY * ((n // len(HIERARCHY)) + 1))[:n]
    total = sum(shares)
    shares = [x / total for x in shares]

    boxes = []
    for s, share in zip(stickers, shares):
        size = box_size(s, share, area_budget, cw, border)
        box_w = size * 1.08 + 2 * border
        box_h = box_w / sticker_aspect(s)
        boxes.append({"size": size, "box_w": box_w, "box_h": box_h})

    radii = [(b["box_w"] + b["box_h"]) / 4 for b in boxes]
    half = [(b["box_w"] / 2, b["box_h"] / 2) for b in boxes]

    # 2. seeded scatter: hero at centre, rest on a golden-angle ring
    order = sorted(range(n), key=lambda i: -boxes[i]["box_w"])
    positions = [[0.0, 0.0] for _ in range(n)]
    golden = math.pi * (3 - math.sqrt(5))
    for rank, i in enumerate(order):
        if rank == 0:
            positions[i] = [cw / 2, ch / 2]
        else:
            r = min(cw, ch) * (0.18 + 0.055 * rank) * (1 + rng.uniform(-0.15, 0.15))
            a = rank * golden + rng.uniform(-0.2, 0.2)
            positions[i] = [cw / 2 + r * math.cos(a), ch / 2 + r * math.sin(a)]

    # 3. relax into the overlap band
    relax(positions, radii, cw, ch, {"half": half})

    # 4. write back — draw order becomes smaller stickers first, hero on top
    #    (the hero is stickers[0], the largest share), so the identity piece
    #    is never buried by its neighbours
    hero = stickers[0]
    ordered = stickers[1:] + [hero]
    by_src = {id(s): (pos, box) for s, pos, box in zip(stickers, positions, boxes)}
    new_stickers = []
    for s in ordered:
        pos, box = by_src[id(s)]
        s["size"] = box["size"]
        s["x"] = round(pos[0], 1)
        s["y"] = round(pos[1], 1)
        s["rotate"] = round(rng.uniform(-tilt, tilt), 1)
        new_stickers.append(s)
    cfg["stickers"] = new_stickers

    (WIDGET / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 5. report
    print(f"suggested layout for {n} stickers on {cw}x{ch} (seed {seed})")
    for s, box in zip(stickers, boxes):
        print(f"  {Path(s['src']).name:<16} size={s['size']:>3} at ({s['x']}, {s['y']}) rotate={s['rotate']}")
    overlaps = []
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(positions[j][0] - positions[i][0], positions[j][1] - positions[i][1])
            overlaps.append(max(0.0, 1 - d / (radii[i] + radii[j])) * 100)
    coverage = sum((b["box_w"] * b["box_h"]) for b in boxes) / (cw * ch) * 100
    print(f"  pairwise overlap: {min(overlaps):.0f}%..{max(overlaps):.0f}% (band {OVERLAP_MIN*100:.0f}..{OVERLAP_MAX*100:.0f}%)")
    print(f"  area coverage: {coverage:.0f}%")


if __name__ == "__main__":
    main()
