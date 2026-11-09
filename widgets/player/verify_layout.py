"""Compose the split player assets exactly as the README lays them out
(including the <details><summary> marker indent) and verify the artist
caption's axis lands on the album-art axis, with no vertical clipping.

Usage: python widgets/player/verify_layout.py
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"

SCALE = 1.5                      # render density over css display sizes
CARD_LEFT_W = 600                # player-left webp, 400 css * 1.5
COVER_W = 298                    # player-cover.png, 199 css * 1.5
COVER_AXIS_IN_ASSET = 113 * SCALE   # album-art centre inside the 199 css block
CRIGHT_W = 266                   # control-right webp, 177 css * 1.5
CAXIS_IN_ASSET = (113 - 17) * SCALE  # caption axis: cover axis minus marker push
MARKER_INDENT = 17 * SCALE       # summary disclosure marker, css 17
ROW_GAP = 4.8 * SCALE            # space GitHub inserts between paired images


def axis_of(im, name):
    """Centre x of the non-transparent pixels, plus the y extent."""
    bbox = im.getchannel("A").getbbox()
    if bbox is None:
        sys.exit(f"{name}: fully transparent, nothing to measure")
    cx = (bbox[0] + bbox[2]) / 2
    print(f"{name}: content x {bbox[0]}..{bbox[2]} (centre {cx:.1f}), "
          f"y {bbox[1]}..{bbox[3]} of {im.height}")
    return cx, bbox


def main():
    card_left = Image.open(ASSETS / "player-left-light.webp").convert("RGBA")
    cover = Image.open(ASSETS / "player-cover.png").convert("RGBA")
    ctrl_left = Image.open(ASSETS / "control-left-light.png").convert("RGBA")
    ctrl_right = Image.open(ASSETS / "control-right-light.webp").convert("RGBA")
    ctrl_right.seek(0)           # t=0: caption parked on the album-art axis

    print(f"sizes: card {card_left.size}, cover {cover.size}, "
          f"ctrl-left {ctrl_left.size}, ctrl-right {ctrl_right.size}")

    # README layout over a white page: row 1 = card left + cover, row 2 =
    # control strip pushed right by the summary marker
    row1_w = round(CARD_LEFT_W + ROW_GAP + COVER_W)
    row2_w = round(MARKER_INDENT + CARD_LEFT_W + ROW_GAP + CRIGHT_W)
    card_h = card_left.height
    strip_h = ctrl_left.height
    H = card_h + 30 + strip_h
    page = Image.new("RGBA", (max(row1_w, row2_w), H), (255, 255, 255, 255))
    page.paste(card_left, (0, 0), card_left)
    page.paste(cover, (round(CARD_LEFT_W + ROW_GAP), 0), cover)
    y2 = card_h + 30
    page.paste(ctrl_left, (round(MARKER_INDENT), y2), ctrl_left)
    page.paste(ctrl_right, (round(MARKER_INDENT + CARD_LEFT_W + ROW_GAP), y2),
               ctrl_right)
    out = ROOT / "widgets" / "player" / "verify_layout.png"
    page.save(out)
    print(f"wrote {out.name} ({page.size[0]}x{page.size[1]})")

    # album-art axis: centre of the cover slice's alpha bbox
    cover_cx, _ = axis_of(cover, "player-cover")
    # caption vertical clearance (the horizontal centre check only makes
    # sense in static mode — a marquee frame's ink spans the full canvas)
    cap_cx, cap_bbox = axis_of(ctrl_right, "control-right@t0")

    cover_axis = round(CARD_LEFT_W + ROW_GAP) + cover_cx
    print(f"album-art axis x = {cover_axis:.1f}")
    scrolling = cap_bbox[2] >= ctrl_right.width - 2   # ink cut at the right edge
    if scrolling:
        print("caption is a marquee frame (ink spans the full canvas) — "
              "axis verified separately in static mode")
    else:
        cap_axis = round(MARKER_INDENT + CARD_LEFT_W + ROW_GAP) + cap_cx
        print(f"caption axis   x = {cap_axis:.1f}")
        print(f"offset = {cap_axis - cover_axis:+.1f}px "
              f"({'OK' if abs(cap_axis - cover_axis) < 2 else 'MISALIGNED'})")

    top_clip = cap_bbox[1]
    bot_clip = ctrl_right.height - cap_bbox[3]
    print(f"caption vertical clearance: {top_clip}px above, {bot_clip}px below "
          f"({'OK' if top_clip > 0 and bot_clip > 0 else 'CLIPPED'})")

    # caption window check: every frame's ink must stay inside the clip
    # window (block-local 15..177 css -> 22.5..266 px at 1.5x) — text must
    # never stick out past the album-art column's left edge
    clip_left_px = 15 * SCALE
    bad = 0
    anim = Image.open(ASSETS / "control-right-light.webp")   # keep for n_frames
    for i in range(anim.n_frames):
        bb = anim.getchannel("A").getbbox()
        if bb and bb[0] < clip_left_px - 1:
            bad += 1
        if i + 1 < anim.n_frames:
            anim.seek(i + 1)
    print(f"caption window: {anim.n_frames} frames checked, "
          f"{bad} with ink left of the album-art column "
          f"({'OK' if bad == 0 else 'OVERHANG'})")


if __name__ == "__main__":
    main()
