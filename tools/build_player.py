"""Regenerate the profile player artwork in assets/.

Inputs
  tools/cover.jpg             album artwork
  tools/qq-player-icons.png   2x icon sheet (QQ Music player sprite)

Outputs
  assets/player-{light,dark}.png     title, lyrics, progress, artwork
  assets/controls-{light,dark}.png   transport row + artist caption

Usage: python tools/build_player.py   (requires Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SCALE = 2  # supersampling factor; output is 2x the CSS size

CARD_W, CARD_H = 599, 172
COVER_SIZE = 162
COVER_LEFT, COVER_TOP = CARD_W - 5 - COVER_SIZE, 5
TEXT_RIGHT = 385

TITLE = "Flower In A Hurricane (feat. Tame Impala, SZA, King Gizzard & the Lizard Wizard)"
LYRIC_CURRENT = "Like a flower in a hurricane"
LYRIC_NEXT = "I will die before I walk away"
LYRIC_FOLLOWING = "Yeah you know"
ELAPSED, DURATION = "01:32", "03:44"
PROGRESS = (60 + 32) / (3 * 60 + 44)
ARTIST = "Justice \u00b7 Tame Impala \u00b7 SZA"

STRIP_W, STRIP_H = 577, 14
ICON_SCALE = 0.74
ICON_CELLS = {
    "next": (0, 80, 30, 120),
    "like": (0, 160, 38, 200),
    "delete": (0, 240, 36, 280),
    "more": (0, 280, 32, 320),
    "dot": (0, 400, 20, 420),
}
CAPTION_CENTER_X = 496  # page-space centre of the cover, in strip coordinates

FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"


def theme_palette(dark: bool) -> dict:
    if dark:
        text = (230, 237, 243)
        muted = (150, 158, 168)
        track = (62, 68, 76)
        accent = (200, 208, 218)
    else:
        text = (51, 51, 51)
        muted = (102, 102, 102)
        track = (230, 230, 230)
        accent = (77, 77, 77)
    return {
        "text": text + (255,),
        "muted": muted + (255,),
        "lyric_next": muted + (130,),
        "lyric_following": muted + (70,),
        "track": track + (255,),
        "accent": accent + (255,),
    }


def font(size: int):
    return ImageFont.truetype(FONT_REGULAR, size * SCALE)


def fit_text(draw, text, fnt, max_width):
    if draw.textlength(text, font=fnt) <= max_width:
        return text
    while text and draw.textlength(text + "\u2026", font=fnt) > max_width:
        text = text[:-1]
    return text.rstrip() + "\u2026"


def tint(sprite_cell, color):
    out = Image.new("RGBA", sprite_cell.size, color)
    out.putalpha(sprite_cell.split()[3])
    return out


def load_cover():
    src = Image.open(ROOT / "tools/cover.jpg").convert("RGBA")
    src = src.resize((COVER_SIZE * SCALE, COVER_SIZE * SCALE), Image.LANCZOS)
    mask = Image.new("L", src.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, src.width - 1, src.height - 1], radius=5 * SCALE, fill=255
    )
    cover = Image.new("RGBA", src.size, (0, 0, 0, 0))
    cover.paste(src, (0, 0), mask)
    return cover


def build_card(theme: str, sprite, cover):
    p = theme_palette(theme == "dark")
    img = Image.new("RGBA", (CARD_W * SCALE, CARD_H * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    img.paste(cover, (COVER_LEFT * SCALE, COVER_TOP * SCALE), cover)

    draw.text(
        (0, 34 * SCALE),
        fit_text(draw, TITLE, font(18), TEXT_RIGHT * SCALE),
        font=font(18), fill=p["text"], anchor="ls",
    )
    for baseline, text, color in (
        (62, LYRIC_CURRENT, p["text"]),
        (80, LYRIC_NEXT, p["lyric_next"]),
        (98, LYRIC_FOLLOWING, p["lyric_following"]),
    ):
        draw.text(
            (0, baseline * SCALE),
            fit_text(draw, text, font(13), TEXT_RIGHT * SCALE),
            font=font(13), fill=color, anchor="ls",
        )

    draw.text((0, 155 * SCALE), ELAPSED, font=font(12), fill=p["muted"], anchor="ls")
    draw.text((TEXT_RIGHT * SCALE, 155 * SCALE), DURATION, font=font(12), fill=p["muted"], anchor="rs")

    bar_left, bar_right, bar_top = 41 * SCALE, 343 * SCALE, 150 * SCALE
    draw.rounded_rectangle([bar_left, bar_top, bar_right, bar_top + 2 * SCALE], radius=SCALE, fill=p["track"])
    knob_x = bar_left + (bar_right - bar_left) * PROGRESS
    draw.rounded_rectangle([bar_left, bar_top, knob_x, bar_top + 2 * SCALE], radius=SCALE, fill=p["accent"])
    dot = sprite.crop(ICON_CELLS["dot"])
    if theme == "dark":
        dot = tint(dot, p["accent"])
    img.paste(dot, (int(knob_x) - 10 * SCALE, bar_top - 3 * SCALE), dot)

    img.save(ROOT / f"assets/player-{theme}.png", optimize=True)


def build_controls(theme: str, sprite):
    p = theme_palette(theme == "dark")
    strip = Image.new("RGBA", (STRIP_W * SCALE, STRIP_H * SCALE), (0, 0, 0, 0))

    def icon(name):
        cell = sprite.crop(ICON_CELLS[name])
        if theme == "dark":
            cell = tint(cell, p["text"])
        return cell.resize(
            (int(cell.width * ICON_SCALE), int(cell.height * ICON_SCALE)), Image.LANCZOS
        )

    def place(name, x, drop, anchor_right=False):
        cell = icon(name)
        if anchor_right:
            x -= cell.width / SCALE
        y = STRIP_H * SCALE - int(38 * ICON_SCALE) + drop
        strip.paste(cell, (int(x * SCALE), int(y)), cell)

    place("next", 0, drop=3)
    place("like", 297, drop=-1, anchor_right=True)
    place("delete", 333, drop=-1, anchor_right=True)
    place("more", 367, drop=-1, anchor_right=True)

    draw = ImageDraw.Draw(strip, "RGBA")
    volume_left, volume_right, volume_top = 33 * SCALE, 83 * SCALE, 6 * SCALE + 3
    draw.rounded_rectangle([volume_left, volume_top, volume_right, volume_top + 2 * SCALE], radius=SCALE, fill=p["track"])
    volume_knob = volume_left + (volume_right - volume_left) * 0.5
    draw.rounded_rectangle([volume_left, volume_top, volume_knob, volume_top + 2 * SCALE], radius=SCALE, fill=p["accent"])
    dot = sprite.crop(ICON_CELLS["dot"])
    if theme == "dark":
        dot = tint(dot, p["accent"])
    dot = dot.resize((round(dot.width * ICON_SCALE), round(dot.height * ICON_SCALE)), Image.LANCZOS)
    strip.paste(dot, (int(volume_knob) - dot.width // 2, volume_top - dot.height // 2 + SCALE), dot)

    draw.text(
        (CAPTION_CENTER_X * SCALE, 12 * SCALE),
        fit_text(draw, ARTIST, font(11), 170 * SCALE),
        font=font(11), fill=p["muted"], anchor="ms",
    )
    strip.save(ROOT / f"assets/controls-{theme}.png", optimize=True)


def main():
    sprite = Image.open(ROOT / "tools/qq-player-icons.png").convert("RGBA")
    cover = load_cover()
    for theme in ("light", "dark"):
        build_card(theme, sprite, cover)
        build_controls(theme, sprite)
    print("wrote assets/player-*.png and assets/controls-*.png")


if __name__ == "__main__":
    main()
