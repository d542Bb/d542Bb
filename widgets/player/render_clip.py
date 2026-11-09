"""Render the animated player card as a lossy animated WebP with real alpha.

Pipeline: rebuild preview.html from the config, open it in headless
Chromium, walk the per-frame schedule the page computed, pull each frame
off the canvas, crop it to the animated left half, and hand the RGBA
frames to libwebp. The encoder keeps transparency per pixel (the card
blends into any GitHub theme — no pinned background), uses replace
blending where frames have transparent regions (sliding lyrics erase
cleanly), and shrinks static stretches to tiny sub-rectangles on its own.

The right half (album art) never animates, so it ships once as a plain
transparent PNG next to the animation.

Usage: python widgets/player/render_clip.py [path/to/config.json]
Needs: playwright (Chromium / Edge), Pillow.
"""

import base64
import io
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

WIDGET = Path(__file__).resolve().parent
ROOT = WIDGET.parents[1]
LEFT_W = 400                     # animated half; card is 599 wide
CAPTURE_CHUNK = 20               # frames per evaluate round-trip
FPS_OPTION = "30"                # matches BASE_FPS in the preview template


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


def downscale(frames):
    """README shows the card at 599 css px, so 1x is the native size."""
    target = (frames[0].width // 2, frames[0].height // 2)
    return [f.resize(target, Image.LANCZOS) for f in frames]


def build_palette(frames):
    """One shared 256-color palette per theme, sampled across the loop.
    Near-duplicate slots are merged: quantization jitter between adjacent
    slots breaks VP8L's run lengths the same way it broke LZW."""
    samples = [frames[i].convert("RGB") for i in
               (0, len(frames) // 4, len(frames) // 2,
                3 * len(frames) // 4, len(frames) - 1)]
    strip = Image.new("RGB", (frames[0].width, frames[0].height * len(samples)))
    for row, im in enumerate(samples):
        strip.paste(im, (0, row * frames[0].height))
    base = strip.quantize(colors=256, method=Image.MEDIANCUT)
    raw = base.getpalette()                       # may be shorter than 256 slots
    slot_count = len(raw) // 3
    entries = list(raw) + [0] * (768 - len(raw))

    lut = list(range(256))
    kept = []
    for i in range(slot_count):
        rgb = entries[i * 3:i * 3 + 3]
        for j in kept:
            if sum((rgb[c] - entries[j * 3 + c]) ** 2 for c in range(3)) < 36:
                lut[i] = j
                break
        else:
            kept.append(i)

    pal = Image.new("P", (1, 1))
    pal.putpalette(entries)
    return pal, lut


def quantize_frame(frame, palette, lut):
    """Collapse a frame onto the shared palette but keep a real alpha plane:
    the 256-color picture is what compresses well, while alpha lets the card
    blend into any page theme. Alpha is binarized — smooth gradients on the
    text edges would dominate the lossless alpha plane's cost — which is
    exactly the look the GIF pipeline had."""
    rgb = frame.convert("RGB")                      # fully transparent px = black
    q = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
    q = q.point(lut)
    out = q.convert("RGB")
    # threshold 64: canvas text is solid or pre-blended solid gray, so only
    # downsampling residue lives below it; anything that low is background
    out.putalpha(frame.getchannel("A").point(lambda a: 255 if a >= 64 else 0))
    return out


def encode_webp(frames, delays_cs, dest):
    """Lossless animated WebP over palette-collapsed frames: VP8L's entropy
    coding is far ahead of the GIF's LZW on the same pixels, the alpha plane
    stays exact, and libwebp picks replace blending for frames with
    transparent regions so sliding lyrics erase cleanly."""
    durations = [round(cs * 10) for cs in delays_cs]   # centiseconds -> ms
    frames[0].save(
        dest, format="WEBP", save_all=True, append_images=frames[1:],
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
        frames = page.evaluate(f"""() => {{
          state.playing = false;
          state.sched = false;
          document.getElementById('fps').value = '{FPS_OPTION}';
          rebuildSchedule();
          return schedule.frames.map(f => ({{ t: f.t, delayCs: f.delayCs }}));
        }}""")
        print(f"schedule: {len(frames)} frames "
              f"({sum(f['delayCs'] for f in frames) / 100:.1f}s total)")
        grabbed = grab_frames(page, frames)
        browser.close()

    delays = [f["delayCs"] for f in frames]
    workdir = Path(tempfile.mkdtemp(prefix="player-frames-"))
    try:
        for theme in ("light", "dark"):
            # cover half: identical in both themes, one static transparent PNG
            cover = grabbed[theme][0].crop((LEFT_W, 0, grabbed[theme][0].width,
                                            grabbed[theme][0].height))
            cover_path = ROOT / "assets" / "player-cover.png"
            cover.save(cover_path, optimize=True)

            left = [f.crop((0, 0, LEFT_W, f.height)) for f in downscale(grabbed[theme])]
            palette, lut = build_palette(left)
            quantized = [quantize_frame(f, palette, lut) for f in left]
            dest = ROOT / "assets" / f"player-left-{theme}.webp"
            size = encode_webp(quantized, delays, dest)
            print(f"wrote {dest.relative_to(ROOT)} ({size / 1024:.0f} KB, "
                  f"{len(quantized)} frames, cover {cover_path.stat().st_size / 1024:.0f} KB)")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
