"""Compose the profile sticker board in assets/ from config.json.

Each sticker image goes through one pipeline:
  1. solidify   — an alpha threshold cuts soft backgrounds, the cut edge is
                  smoothed at source resolution, floating debris is dropped
                  and enclosed holes are filled: one clean die-cut silhouette
  2. harmonise  — lightness, saturation and shadow tone are nudged toward
                  shared targets, so differently coloured stickers read as
                  one design system
  3. material   — enamel finish: soft bevelled rim, glossy sweep, fine grain
  4. frame      — white outline with contact + thickness shading
  5. place      — tilt, diffuse drop shadow (all shadows under all stickers),
                  compose on a transparent canvas

Inputs
  config.json        canvas size, sticker placements, render defaults
  stickers/          raw sticker images (transparent PNGs work best)

Outputs
  assets/stickers.png

Usage: python widgets/stickers/build.py   (requires Pillow)
"""

import json
import math
import random
import zlib
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageStat

ROOT = Path(__file__).resolve().parents[2]   # repo root (assets/ lives here)
WIDGET = Path(__file__).resolve().parent     # this widget's folder
SCALE = 2  # supersampling factor; output is 2x the CSS size

DEFAULT_BORDER = 9          # white outline width, logical px
DEFAULT_ALPHA_THRESHOLD = 250  # alpha below this counts as background (0 = keep everything)
EDGE_SMOOTH = 0.005         # cut-edge smoothing radius, fraction of source width
SHADOW_OFFSET_PCT = 0.024   # drop shadow offset, fraction of sticker width
SHADOW_BLUR_PCT = 0.052     # drop shadow blur, fraction of sticker width
SHADOW_OPACITY = 55         # 0-255
SHADOW_COLOR = (32, 34, 42)

# Shared material + colour settings: every sticker comes out of one design
# system regardless of what image it started from.
HARMONIZE_TARGET_L = 0.50   # aim for mean perceived lightness, 0-1
HARMONIZE_TARGET_S = 0.60   # aim for mean saturation, 0-1
HARMONIZE_CLAMP = 0.18      # max nudge in either direction (keeps identity)
SHADOW_TINT = (46, 44, 62)  # every sticker's darks lean toward this ink tone
SHADOW_TINT_STRENGTH = 0.20
SHADOW_TINT_MAX_L = 70      # only pixels darker than this are tinted
BEVEL_LIGHT, BEVEL_DARK = 42, 34   # enamel rim strength, 0-255
BEVEL_WIDTH = 0.045         # rim band width, fraction of art width
SHEEN_STRENGTH = 60         # glossy sweep peak, 0-255
GRAIN_STRENGTH = 10         # surface grain amplitude, 0-255
GRAIN_VISIBILITY = 6        # grain overlay opacity, 0-255
RING_SHADE = (178, 176, 188)       # white-border shading tone
RING_SHADE_STRENGTH = 76           # 0-255


def load_config():
    return json.loads((WIDGET / "config.json").read_text(encoding="utf-8"))


def binarize(img: Image.Image, threshold: int, smooth_radius: int):
    """Cut a soft/semi-transparent background at `threshold`.

    The binary cut is smoothed (blur + re-threshold) at source resolution,
    where anti-aliased hand-drawn edges are 10-100px wide, so the silhouette
    comes out with clean curves instead of threshold jaggies. Returns
    (image, solid_mask) trimmed to the solid shape, or (img, None) when
    thresholding is disabled.
    """
    if threshold <= 0:
        bbox = img.getchannel("A").getbbox()
        return (img.crop(bbox) if bbox else img), None
    solid = img.getchannel("A").point(lambda v: 255 if v >= threshold else 0)
    if smooth_radius > 0:
        solid = solid.filter(ImageFilter.GaussianBlur(smooth_radius))
        solid = solid.point(lambda v: 255 if v >= 128 else 0)
    bbox = solid.getbbox()
    if not bbox:
        return img, None
    return img.crop(bbox), solid.crop(bbox)


def keep_main_components(mask: Image.Image, min_ratio: float) -> Image.Image:
    """Drop connected components much smaller than the largest one."""
    if min_ratio <= 0:
        return mask
    w, h = mask.size
    data = mask.tobytes()
    visited = bytearray(w * h)
    components = []
    for start in range(w * h):
        if visited[start] or data[start] < 128:
            continue
        visited[start] = 1
        stack = [start]
        cells = []
        while stack:
            j = stack.pop()
            cells.append(j)
            jx, jy = j % w, j // w
            for nx, ny in ((jx + 1, jy), (jx - 1, jy), (jx, jy + 1), (jx, jy - 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    k = ny * w + nx
                    if not visited[k] and data[k] >= 128:
                        visited[k] = 1
                        stack.append(k)
        components.append(cells)
    if len(components) <= 1:
        return mask
    largest = max(len(c) for c in components)
    out = Image.new("L", mask.size, 0)
    op = out.load()
    for cells in components:
        if len(cells) >= largest * min_ratio:
            for j in cells:
                op[j % w, j // w] = 255
    return out


def fill_holes(mask: Image.Image) -> Image.Image:
    """Fill enclosed transparent areas so the silhouette is one solid cut."""
    w, h = mask.size
    padded = Image.new("L", (w + 2, h + 2), 0)
    padded.paste(mask, (1, 1))
    outside = padded.point(lambda v: 255 - v)
    ImageDraw.floodfill(outside, (0, 0), 128)  # reachable empty area -> 128
    holes = outside.point(lambda v: 255 if v == 255 else 0)  # unreachable = holes
    return ImageChops.lighter(padded, holes).crop((1, 1, w + 1, h + 1))


def erode_exact(mask: Image.Image, radius: int) -> Image.Image:
    return ImageChops.invert(dilate_exact(ImageChops.invert(mask), radius))


def close_exact(mask: Image.Image, radius: int) -> Image.Image:
    """Morphological closing with an exact disk: fills concave notches and
    rasterisation stairs without the diagonal distortion of square kernels.
    Pads internally — silhouettes arrive tightly cropped, and a dilation
    without headroom gets clipped flat against the canvas edge (octagons)."""
    if radius <= 0:
        return mask
    m = radius + 2
    padded = Image.new("L", (mask.width + 2 * m, mask.height + 2 * m), 0)
    padded.paste(mask, (m, m))
    closed = erode_exact(dilate_exact(padded, radius), radius)
    return closed.crop((m, m, m + mask.width, m + mask.height))


def harden(mask: Image.Image) -> Image.Image:
    """Compress a wide alpha ramp to ~1 logical px of anti-aliasing.

    Artwork printed on a die-cut sticker runs solid to the cut line; a soft
    alpha ramp over the white border reads as a faded, dirty fringe.
    """
    lo, hi = 96, 160
    lut = [0 if v <= lo else 255 if v >= hi else (v - lo) * 255 // (hi - lo) for v in range(256)]
    return mask.point(lut)


def solidify(mask: Image.Image, item: dict, defaults: dict) -> Image.Image:
    opts = {**defaults.get("solidify", {}), **item.get("solidify", {})}
    if opts.get("min_keep", 0.04) > 0:
        mask = keep_main_components(mask, opts.get("min_keep", 0.04))
    if opts.get("fill_holes", True):
        mask = fill_holes(mask)
    # Exact-disk closing, then re-soften: square-kernel closing measurably
    # wobbles the silhouette (visible as polygonal borders on round stickers).
    return close_exact(mask, opts.get("close", 2) * SCALE).filter(
        ImageFilter.GaussianBlur(SCALE)
    )


def dilate_exact(mask: Image.Image, radius: int) -> Image.Image:
    """Exact Euclidean dilation: the outline moves out by exactly `radius`
    px in every direction.

    Square-kernel morphological dilation offsets diagonals 41% further than
    the axes, which turns a circular sticker's border into a rounded octagon.
    This computes the true Euclidean distance-to-shape field (Felzenszwalb-
    Huttenlocher, separable 1-D passes) and thresholds it at `radius`.
    """
    if radius <= 0:
        return mask
    w, h = mask.size
    solid = mask.tobytes()
    INF = 1e20
    limit = float(radius * radius)

    def _squared_dt(src):
        # exact squared distance transform along a 1-D line
        n = len(src)
        d = [0.0] * n
        v = [0] * n
        z = [-INF] * (n + 1)
        k = 0
        for q in range(1, n):
            s = ((src[q] + q * q) - (src[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
            while s <= z[k]:
                k -= 1
                s = ((src[q] + q * q) - (src[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
            k += 1
            v[k] = q
            z[k] = s
            z[k + 1] = INF
        k = 0
        for q in range(n):
            while z[k + 1] < q:
                k += 1
            d[q] = (q - v[k]) ** 2 + src[v[k]]
        return d

    grid = [
        _squared_dt([0.0 if solid[y * w + x] >= 128 else INF for y in range(h)])
        for x in range(w)
    ]
    out = bytearray(w * h)
    for y in range(h):
        row = _squared_dt([grid[x][y] for x in range(w)])
        base = y * w
        for x in range(w):
            if row[x] <= limit:
                out[base + x] = 255
    return Image.frombytes("L", (w, h), bytes(out))


def harmonize(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Nudge lightness, saturation and shadow tone toward shared targets."""
    flat = Image.new("RGB", rgb.size, (128, 128, 128))
    flat.paste(rgb, (0, 0), alpha)  # stats over a neutral background

    lightness = ImageStat.Stat(flat.convert("L")).mean[0] / 255
    if 0.02 < lightness < 0.98:
        gamma = math.log(HARMONIZE_TARGET_L) / math.log(lightness)
        gamma = min(max(gamma, 1 - HARMONIZE_CLAMP), 1 + HARMONIZE_CLAMP)
        lut = [round(255 * (i / 255) ** gamma) for i in range(256)]
        rgb = rgb.point(lut * 3)
        flat = flat.point(lut * 3)

    sat = ImageStat.Stat(flat.convert("HSV").split()[1]).mean[0] / 255
    if sat > 0.01:
        factor = HARMONIZE_TARGET_S / sat
        rgb = ImageEnhance.Color(rgb).enhance(
            min(max(factor, 1 - HARMONIZE_CLAMP), 1 + HARMONIZE_CLAMP)
        )

    dark = rgb.convert("L").point(lambda v: max(0, 255 - v * 255 // SHADOW_TINT_MAX_L))
    dark = ImageChops.multiply(dark, alpha)
    tinted = Image.blend(rgb, Image.new("RGB", rgb.size, SHADOW_TINT), SHADOW_TINT_STRENGTH)
    return Image.composite(tinted, rgb, dark)


def apply_material(rgb: Image.Image, alpha: Image.Image, seed_name: str) -> Image.Image:
    """Enamel-sticker finish: bevelled rim, glossy sweep, fine grain."""
    size = rgb.size
    w, _ = size
    white = Image.new("RGB", size, (255, 255, 255))

    r = max(3 * SCALE, round(w * BEVEL_WIDTH))  # rim band width
    inner = alpha.filter(ImageFilter.MinFilter(2 * r + 1)).filter(ImageFilter.GaussianBlur(2 * SCALE))
    d = max(2 * SCALE, r // 2)
    light_band = ImageChops.subtract(inner, ImageChops.offset(inner, d, d))
    dark_band = ImageChops.subtract(inner, ImageChops.offset(inner, -d, -d))
    rgb.paste(white, (0, 0), light_band.point(lambda v: v * BEVEL_LIGHT // 255))
    rgb.paste(Image.new("RGB", size, (0, 0, 0)), (0, 0), dark_band.point(lambda v: v * BEVEL_DARK // 255))

    gloss = Image.new("L", size, 0)
    ImageDraw.Draw(gloss).ellipse(
        [-round(w * 0.30), -round(w * 0.55), round(w * 0.95), round(w * 0.45)], fill=255
    )
    gloss = gloss.filter(ImageFilter.GaussianBlur(max(2 * SCALE, w // 14)))
    rgb.paste(white, (0, 0), ImageChops.multiply(gloss, alpha).point(lambda v: v * SHEEN_STRENGTH // 255))

    rng = random.Random(zlib.crc32(seed_name.encode("utf-8")))
    cell = 48
    noise = Image.new("L", (cell, cell))
    noise.putdata([rng.randint(128 - GRAIN_STRENGTH, 128 + GRAIN_STRENGTH) for _ in range(cell * cell)])
    noise = noise.resize(size, Image.BILINEAR).convert("RGB")
    rgb.paste(noise, (0, 0), alpha.point(lambda v: v * GRAIN_VISIBILITY // 255))

    return rgb


def resize_art(img: Image.Image, size: tuple) -> Image.Image:
    """LANCZOS resize in premultiplied alpha.

    Resampling straight-alpha RGBA mixes edge colours with the transparent
    pixels' black, leaving a dark fringe when the art is composited over the
    white border. Premultiply → resize → unpremultiply keeps edge pixels the
    pure artwork colour at partial coverage.
    """
    r, g, b, a = img.split()
    pm = Image.merge(
        "RGBA",
        (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a),
    ).resize(size, Image.LANCZOS)
    out = Image.new("RGBA", size)
    op = out.load()
    pp = pm.load()
    for y in range(size[1]):
        for x in range(size[0]):
            ro, go, bo, ao = pp[x, y]
            if ao == 0:
                op[x, y] = (0, 0, 0, 0)
            elif ao == 255:
                op[x, y] = (ro, go, bo, 255)
            else:
                op[x, y] = (
                    min(255, ro * 255 // ao),
                    min(255, go * 255 // ao),
                    min(255, bo * 255 // ao),
                    ao,
                )
    return out


def prep_sticker(path: Path, item: dict, defaults: dict) -> Image.Image:
    """Clean, harmonise, frame and finish one sticker image."""
    size = item.get("size", defaults.get("size", 80))
    border = item.get("border", defaults.get("border", DEFAULT_BORDER))
    threshold = item.get("alpha_threshold", defaults.get("alpha_threshold", DEFAULT_ALPHA_THRESHOLD))

    img = Image.open(path).convert("RGBA")
    img, solid = binarize(img, threshold, round(img.width * EDGE_SMOOTH))
    opaque_source = img.getchannel("A").getextrema()[0] == 255
    # Judge "real artwork vs faint junk" at source resolution: after resizing,
    # the art's own anti-aliased edge would be misjudged as junk and whitened.
    art_src = img.getchannel("A").point(lambda v: 255 if v >= 248 else 0)

    factor = SCALE * size / img.width
    img = resize_art(img, (round(img.width * factor), round(img.height * factor)))
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")

    if opaque_source:
        # fully opaque source: round it so the outline frames a card, not a box
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, img.width - 1, img.height - 1],
            radius=round(min(img.size) * 0.12), fill=255,
        )
        alpha = mask
    elif solid is not None:
        # keep the soft anti-aliased edge from the downscaled smooth cut
        solid = solid.resize(img.size, Image.LANCZOS)
        solid = solidify(solid, item, defaults)
        # Faint junk near the edge (speed-line remnants, hole fillings) would
        # print as grey smudges on the white frame: recolor it to white so it
        # merges with the border. Real artwork stays untouched.
        core = solid.filter(ImageFilter.MinFilter(3 * border * SCALE + 1))
        art = art_src.resize(img.size, Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
        junk = ImageChops.multiply(ImageChops.subtract(solid, core), ImageChops.invert(art))
        rgb = Image.composite(Image.new("RGB", img.size, (255, 255, 255)), rgb, junk)
        # Holes that solidify filled were empty in the source: their pixels
        # carry resize garbage (transparent black), so print them as the
        # sticker's white backing paper instead.
        orig_solid = alpha.point(lambda v: 255 if v >= 128 else 0)
        filled = ImageChops.subtract(solid.point(lambda v: 255 if v >= 128 else 0), orig_solid)
        rgb = Image.composite(Image.new("RGB", img.size, (255, 255, 255)), rgb, filled)
        alpha = harden(solid)

    if item.get("harmonize", defaults.get("harmonize", True)):
        rgb = harmonize(rgb, alpha)
    if item.get("material", defaults.get("material", True)):
        rgb = apply_material(rgb, alpha, path.name)

    img = rgb.convert("RGBA")
    img.putalpha(alpha)

    if border <= 0:
        return img

    # Dilate the alpha channel to grow the silhouette outwards, then paste a
    # white silhouette under the sticker: the classic die-cut frame. The alpha
    # is padded with headroom first so dilation and blur aren't clipped.
    b = border * SCALE
    pad = 2 * SCALE
    padded = Image.new("L", (img.width + 2 * b + 2 * pad, img.height + 2 * b + 2 * pad), 0)
    padded.paste(alpha, (b + pad, b + pad))
    grown = dilate_exact(padded, b).filter(ImageFilter.GaussianBlur(SCALE // 2))
    framed = Image.new("RGBA", padded.size, (0, 0, 0, 0))
    framed.paste(Image.new("RGBA", framed.size, (255, 255, 255, 255)), (0, 0), grown)

    # Shade the white ring so the sticker reads as raised off the page: a
    # contact shadow where the art meets the border and a thin band along the
    # outer edge, both stronger toward the bottom (light comes from above).
    ring = ImageChops.subtract(grown, padded)
    vertical = Image.linear_gradient("L").resize(padded.size).point(
        lambda v: min(255, 96 + v * 2 // 3)
    )
    contact = ImageChops.multiply(ring, padded.filter(ImageFilter.MaxFilter(4 * SCALE + 1)))
    thickness = ImageChops.subtract(grown, grown.filter(ImageFilter.MinFilter(2 * SCALE + 1)))
    shade = ImageChops.multiply(
        ImageChops.lighter(contact, thickness), vertical
    ).filter(ImageFilter.GaussianBlur(2 * SCALE))
    framed.paste(
        Image.new("RGBA", framed.size, RING_SHADE + (255,)), (0, 0),
        shade.point(lambda v: v * RING_SHADE_STRENGTH // 255),
    )

    framed.paste(img, (b + pad, b + pad), img)
    return framed


def paste_layer(canvas: Image.Image, layer: Image.Image, left: int, top: int):
    """alpha_composite that also tolerates negative positions (clips them)."""
    if left < 0:
        layer = layer.crop((-left, 0, layer.width, layer.height))
        left = 0
    if top < 0:
        layer = layer.crop((0, -top, layer.width, layer.height))
        top = 0
    canvas.alpha_composite(layer, (left, top))


def build_layer(item: dict, defaults: dict):
    sticker = prep_sticker(WIDGET / item["src"], item, defaults)

    angle = item.get("rotate", 0)
    if angle == "random":
        # deterministic per sticker: the board stays stable across builds
        rng = random.Random("rotate:" + item["src"])
        angle = rng.uniform(-15, 15)
    if angle:
        sticker = sticker.rotate(angle, expand=True, resample=Image.BICUBIC)

    left = round(item["x"] * SCALE - sticker.width / 2)
    top = round(item["y"] * SCALE - sticker.height / 2)

    shadow, shadow_left, shadow_top = None, 0, 0
    spread = 0
    if item.get("shadow", True):
        # Shadow geometry scales linearly with the sticker's rendered width so
        # small and large stickers keep the same relative shadow weight.
        offset = max(2, round(sticker.width / SCALE * SHADOW_OFFSET_PCT)) * SCALE
        blur = max(4, round(sticker.width / SCALE * SHADOW_BLUR_PCT)) * SCALE
        spread = 2 * blur + offset
        # Blur on a padded canvas: the glow needs room to spread, otherwise it
        # is cut off at the sticker's own bounding box and leaves straight
        # edges behind.
        m = blur * 3
        padded = Image.new("L", (sticker.width + 2 * m, sticker.height + 2 * m), 0)
        padded.paste(sticker.getchannel("A"), (m, m))
        blurred = padded.filter(ImageFilter.GaussianBlur(blur))
        shadow = Image.new("RGBA", padded.size, (0, 0, 0, 0))
        shadow.paste(Image.new("RGBA", padded.size, SHADOW_COLOR + (SHADOW_OPACITY,)), (0, 0), blurred)
        shadow_left, shadow_top = left - m, top + offset - m

    return sticker, shadow, left, top, shadow_left, shadow_top, spread


def main():
    cfg = load_config()
    defaults = cfg.get("defaults", {})
    layers = [build_layer(item, defaults) for item in cfg["stickers"]]

    if cfg.get("fit", defaults.get("fit", True)):
        # Grow the output to hold every sticker and its shadow instead of
        # truncating them at the configured frame: straight cuts at the sheet
        # edge are what a sticker sheet must never have. The shadow is only
        # followed to ~2 sigma — beyond that it is too faint to see.
        xs0, ys0, xs1, ys1 = [], [], [], []
        for sticker, shadow, left, top, _, _, spread in layers:
            xs0 += [left, left - spread if shadow else left]
            ys0 += [top, top - spread if shadow else top]
            xs1 += [left + sticker.width, left + sticker.width + (spread if shadow else 0)]
            ys1 += [top + sticker.height, top + sticker.height + (spread if shadow else 0)]
        margin = SCALE
        min_x, min_y = min(xs0) - margin, min(ys0) - margin
        max_x, max_y = max(xs1) + margin, max(ys1) + margin
        ox, oy = -min_x, -min_y
        width = (max_x - min_x + SCALE - 1) // SCALE
        height = (max_y - min_y + SCALE - 1) // SCALE
    else:
        ox, oy = 0, 0
        width, height = cfg["canvas"]["width"], cfg["canvas"]["height"]

    canvas = Image.new("RGBA", (width * SCALE, height * SCALE), (0, 0, 0, 0))
    # Every shadow under every sticker: a neighbour never casts a dirty grey
    # patch onto another sticker's face.
    for _, shadow, _, _, sl, st, _ in layers:
        if shadow:
            paste_layer(canvas, shadow, sl + ox, st + oy)
    for sticker, _, left, top, _, _, _ in layers:
        paste_layer(canvas, sticker, left + ox, top + oy)

    canvas.resize((width, height), Image.LANCZOS).save(ROOT / "assets/stickers.png", optimize=True)
    print(f"wrote assets/stickers.png ({width}x{height})")


if __name__ == "__main__":
    main()
