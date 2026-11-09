"""Compose the merged player assets exactly as the README lays them out
(including the <details><summary> marker indent) and verify the artist
caption's axis lands on the album-art axis, the caption never sticks out
left of the album-art column, and the caption itself isn't clipped.

Usage: python widgets/player/verify_layout.py
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"

SCALE = 1.5                      # render density over css display sizes
CARD_AXIS = 513 * SCALE          # album-art centre inside the card (css 513)
CAPTION_AXIS = 496 * SCALE       # caption axis inside the strip (css 496 = 513-17)
# no man's land between the transport icons (end css 400) and the caption
# window (starts css 415): the caption must never appear here
NOMANS = (403 * SCALE, 413 * SCALE)
MARKER_INDENT = 17 * SCALE       # summary disclosure marker, css 17


def main():
    card = Image.open(ASSETS / "player-light.webp").convert("RGBA")
    ctrl = Image.open(ASSETS / "control-light.webp").convert("RGBA")
    card.seek(0)
    ctrl.seek(0)                 # t=0: caption parked on the album-art axis

    print(f"sizes: card {card.size}, ctrl {ctrl.size}")

    # README layout over a white page: card on top, strip below pushed right
    # by the summary marker
    H = card.height + 30 + ctrl.height
    page = Image.new("RGBA", (card.width + round(MARKER_INDENT), H),
                     (255, 255, 255, 255))
    page.paste(card, (0, 0), card)
    page.paste(ctrl, (round(MARKER_INDENT), card.height + 30), ctrl)
    out = ROOT / "widgets" / "player" / "verify_layout.png"
    page.save(out)
    print(f"wrote {out.name} ({page.size[0]}x{page.size[1]})")

    # album-art axis: the card asset carries the cover intrinsically; measure
    # its ink centre right of the title band (title clip ends at css 385)
    cover_zone = card.crop((round(400 * SCALE), 0, card.width, card.height))
    bb = cover_zone.getchannel("A").getbbox()
    cover_axis = round(400 * SCALE) + (bb[0] + bb[2]) / 2
    print(f"album-art axis x = {cover_axis:.1f} (expected {CARD_AXIS:.1f}, "
          f"offset {cover_axis - CARD_AXIS:+.1f}px)")

    # caption ink inside its window: bbox and vertical clearance (marquee
    # frames fill the window, so the centre check runs in static mode only)
    win = ctrl.crop((round(415 * SCALE), 0, ctrl.width, ctrl.height))
    wbb = win.getchannel("A").getbbox()
    cap_cx = round(415 * SCALE) + (wbb[0] + wbb[2]) / 2
    top_clip, bot_clip = wbb[1], win.height - wbb[3]
    print(f"caption ink in window: x {wbb[0]}..{wbb[2]} "
          f"(centre {cap_cx:.1f}, expected {CAPTION_AXIS:.1f} when static), "
          f"y clearance {top_clip}px above / {bot_clip}px below "
          f"({'OK' if top_clip > 0 and bot_clip > 0 else 'CLIPPED'})")

    # no man's land: every frame must leave the strip between the icons and
    # the caption window empty — that is what stops the caption sticking
    # out left of the album-art column
    bad = 0
    anim = Image.open(ASSETS / "control-light.webp")   # keep for n_frames
    region = (round(NOMANS[0]), 0, round(NOMANS[1]), anim.height)
    for i in range(anim.n_frames):
        if anim.crop(region).getchannel("A").getbbox() is not None:
            bad += 1
        if i + 1 < anim.n_frames:
            anim.seek(i + 1)
    print(f"no man's land {region[:2]}..{region[2:]}: {anim.n_frames} frames "
          f"checked, {bad} with ink ({'OK' if bad == 0 else 'OVERHANG'})")


if __name__ == "__main__":
    main()
