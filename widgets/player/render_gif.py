"""Render the animated player card GIFs from the preview page.

Pipeline: rebuild preview.html from the config, open it in headless
Chromium, walk the per-frame schedule the page itself computed (timestamps
plus per-frame delays in centiseconds), pull each frame straight off the
canvas as PNG, then assemble both themes into GIFs with Pillow — variable
frame delays included, so idle stretches cost almost nothing.

Usage: python widgets/player/render_gif.py [path/to/config.json]
Needs: playwright (Chromium, or MS Edge on Windows), Pillow.
"""

import base64
import io
import sys
import time
from pathlib import Path

from PIL import Image

WIDGET = Path(__file__).resolve().parent
ROOT = WIDGET.parents[1]
PAGE_BG = {"light": (255, 255, 255), "dark": (13, 17, 23)}
TRANSPARENT_INDEX = 255     # reserved palette slot, used by the 4 corners only
CAPTURE_CHUNK = 20          # frames per evaluate round-trip
OUTPUT_SCALE = 1            # 1 = native README size (599x172); 2 = retina-sharp, 4x bytes


def downscale(frames):
    if OUTPUT_SCALE >= 2:
        return frames
    target = (frames[0].width // 2, frames[0].height // 2)
    return [f.resize(target, Image.LANCZOS) for f in frames]


def launch_chromium(pw):
    attempts = ({}, {"channel": "msedge"})       # CI chromium first, Edge fallback
    last = None
    for kwargs in attempts:
        try:
            return pw.chromium.launch(headless=True, **kwargs)
        except Exception as exc:                 # noqa: BLE001 - probe both runtimes
            last = exc
    raise RuntimeError(f"no usable Chromium/Edge browser: {last}")


def grab_frames(page, frames):
    """Pull every scheduled frame off both card canvases as PIL images."""
    started = time.time()
    light, dark = [], []
    for i in range(0, len(frames), CAPTURE_CHUNK):
        chunk = frames[i:i + CAPTURE_CHUNK]
        data = page.evaluate(
            """(ts) => ts.map(t => {
                 state.t = t;
                 render();
                 return [cardLight.toDataURL('image/png'),
                         cardDark.toDataURL('image/png')];
               })""",
            [f["t"] for f in chunk],
        )
        for light_uri, dark_uri in data:
            for sink, uri in ((light, light_uri), (dark, dark_uri)):
                raw = base64.b64decode(uri.split(",", 1)[1])
                sink.append(Image.open(io.BytesIO(raw)).convert("RGBA"))
        print(f"  captured {min(i + CAPTURE_CHUNK, len(frames))}/{len(frames)} "
              f"frames ({time.time() - started:.0f}s)")
    return {"light": light, "dark": dark}


def composite(frames, bg_rgb):
    """Flatten onto the exact page background. GIF's transparent index means
    "skip this pixel" during inter-frame compositing, so transparency must be
    limited to the four rounded corners (which never change and never enter
    the per-frame delta boxes) — the card interior must stay opaque or
    sliding lyrics could never be erased."""
    bg = Image.new("RGBA", frames[0].size, bg_rgb + (255,))
    return [Image.alpha_composite(bg, f) for f in frames]


def build_palette(flattened, bg_rgb):
    """One global palette per theme, sampled across the loop. Near-duplicate
    slots are merged back onto one index — otherwise quantization jitter in
    flat areas walks between adjacent slots and wrecks the LZW run lengths.
    The slot closest to the page background is rewritten to the exact color
    so the card blends into the page with zero seam; slot 255 stays reserved
    for the rounded corners."""
    samples = [flattened[i].convert("RGB") for i in
               (0, len(flattened) // 4, len(flattened) // 2,
                3 * len(flattened) // 4, len(flattened) - 1)]
    strip = Image.new("RGB", (flattened[0].width, flattened[0].height * len(samples)))
    for row, im in enumerate(samples):
        strip.paste(im, (0, row * flattened[0].height))
    base = strip.quantize(colors=255, method=Image.MEDIANCUT)
    entries = list(base.getpalette()[:255 * 3])

    lut = list(range(256))                     # remap duplicate slots to a keeper
    kept = []
    for i in range(255):
        rgb = entries[i * 3:i * 3 + 3]
        for j in kept:
            if sum((rgb[c] - entries[j * 3 + c]) ** 2 for c in range(3)) < 36:
                lut[i] = j
                break
        else:
            kept.append(i)

    nearest = min(kept, key=lambda i: sum(
        (entries[i * 3 + c] - bg_rgb[c]) ** 2 for c in range(3)))
    for c in range(3):
        entries[nearest * 3 + c] = bg_rgb[c]

    pal = Image.new("P", (1, 1))
    pal.putpalette(entries + [0, 0, 0])
    return pal, lut


def quantize_frame(frame, palette, lut):
    """Map a frame onto the shared palette, collapse merged slots, and give
    the rounded corners (transparent in the source) the reserved index."""
    q = frame.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
    q = q.point(lut)
    mask = frame.getchannel("A").point(lambda a: 255 if a < 128 else 0)
    q.paste(TRANSPARENT_INDEX, mask)
    return q


def quantize_frames(frames, bg_rgb):
    """Map every frame onto one shared per-theme palette. The 256-color step
    is what keeps the encode small: flat text and background colors collapse
    into long single-index runs that both the GIF encoder and VP8L love.
    No dithering: Floyd-Steinberg error diffusion smears quantization noise
    from the moving title band across the whole frame, which defeats the
    per-frame delta boxes and leaves ghost rows on the accumulated canvas."""
    flattened = composite(frames, bg_rgb)
    palette, lut = build_palette(flattened, bg_rgb)
    return [quantize_frame(f, palette, lut) for f in flattened]


def encode_webp(quantized, delays_cs, dest):
    """Animated WebP, lossless, from the palette-quantized frames. Lossless
    means the text is pixel-exact and there is no 256-color seam; VP8L's
    entropy coding beats the GIF's LZW on the same pixels (~40% smaller).
    kmin/kmax keep keyframes sparse so inter-frame deltas stay cheap."""
    rgba = []
    for q in quantized:
        im = q.convert("RGB")                    # transparency slot is black
        alpha = q.point(lambda i: 0 if i == TRANSPARENT_INDEX else 255, mode="L")
        im.putalpha(alpha)
        rgba.append(im)
    durations = [round(cs * 10) for cs in delays_cs]
    rgba[0].save(
        dest, format="WEBP", save_all=True, append_images=rgba[1:],
        duration=durations, loop=0,
        lossless=True, method=6, kmin=50, kmax=100,
    )
    return dest.stat().st_size


def main():
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else WIDGET / "config.json"

    import preview
    html_path = preview.build_html(config_path)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = launch_chromium(pw)
        page = browser.new_page()
        page.goto(html_path.as_uri())
        page.wait_for_function("window.__previewReady === true")
        frames = page.evaluate("""() => {
          state.playing = false;
          state.sched = false;
          document.getElementById('fps').value = '25';
          rebuildSchedule();
          return schedule.frames.map(f => ({ t: f.t, delayCs: f.delayCs }));
        }""")
        print(f"schedule: {len(frames)} frames "
              f"({sum(f['delayCs'] for f in frames) / 100:.1f}s total)")
        grabbed = grab_frames(page, frames)
        # quantize once, encode the lossless WebP per theme
        for theme in ("light", "dark"):
            scaled = downscale(grabbed[theme])
            quantized = quantize_frames(scaled, PAGE_BG[theme])
            delays = [f["delayCs"] for f in frames]
            size = encode_webp(quantized, delays,
                               ROOT / "assets" / f"player-{theme}.webp")
            print(f"wrote {theme} webp ({size / 1024:.0f} KB, "
                  f"{len(quantized)} frames)")
        browser.close()


if __name__ == "__main__":
    main()
