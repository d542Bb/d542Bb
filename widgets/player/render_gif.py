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


def encode_gif(frames, delays_cs, dest, bg_rgb):
    flattened = composite(frames, bg_rgb)
    palette, lut = build_palette(flattened, bg_rgb)
    # No dithering: Floyd-Steinberg error diffusion smears quantization noise
    # from the moving title band across the whole frame, which defeats the
    # per-frame delta boxes and leaves ghost rows on the accumulated canvas.
    quantized = [quantize_frame(f, palette, lut) for f in flattened]
    durations = [round(cs * 10) for cs in delays_cs]   # centiseconds -> ms
    quantized[0].save(
        dest, save_all=True, append_images=quantized[1:],
        duration=durations, loop=0,
        transparency=TRANSPARENT_INDEX, disposal=1,
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
        browser.close()

    for theme in ("light", "dark"):
        dest = ROOT / "assets" / f"player-{theme}.gif"
        size = encode_gif(grabbed[theme],
                          [f["delayCs"] for f in frames], dest, PAGE_BG[theme])
        print(f"wrote {dest.relative_to(ROOT)} ({size / 1024:.0f} KB, "
              f"{len(grabbed[theme])} frames)")


if __name__ == "__main__":
    main()
