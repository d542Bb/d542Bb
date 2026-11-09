"""Render the animated player card as lossless animated WebP assets.

Pipeline: rebuild preview.html from the config, open it in headless
Chromium, walk the per-frame schedule the page computed, pull frames off
the canvases, and encode:

  player-{theme}.webp   the full 599px card (title/lyrics/progress/cover)
  control-{theme}.webp  the full 577px transport strip + artist caption

Each row is a single animated image so the README scales it as a whole
(two adjacent images wrap at narrow widths). Static regions — the cover
art, the transport icons — are identical across frames, so the delta
frames never rewrite them; they appear once, in the first keyframe (the
encoder runs with keyframe insertion disabled, which lossless allows).

Frames are captured at 2x from the canvases, downscaled to OUTPUT_SCALE
(1.5 = the README's display size plus half), collapsed onto a shared
256-color palette with a real alpha plane, and packed losslessly: VP8L's
entropy coding is far ahead of the GIF's LZW on these flat colors, the
alpha plane stays exact, and libwebp picks replace blending for frames
with transparent regions so sliding lyrics erase cleanly on any theme.

Usage: python widgets/player/render_clip.py [path/to/config.json]
Needs: playwright (Chromium / Edge), Pillow.
"""

import base64
import io
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageChops

WIDGET = Path(__file__).resolve().parent
ROOT = WIDGET.parents[1]
CAPTURE_CHUNK = 20               # frames per evaluate round-trip
FPS_OPTION = "25"                # matches BASE_FPS in the preview template
OUTPUT_SCALE = 1.5               # render density over the css display size


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
    """Pull every scheduled frame off the card and strip canvases as PIL
    images. Static regions are identical in every frame; dedupe() and the
    delta encoding take care of the rest."""
    started = time.time()
    streams = {"cardL": [], "cardD": [], "stripL": [], "stripD": []}
    keys = ("cardL", "cardD", "stripL", "stripD")
    for i in range(0, len(frames), CAPTURE_CHUNK):
        chunk = frames[i:i + CAPTURE_CHUNK]
        data = page.evaluate(
            """(ts) => ts.map(t => {
                 state.t = t;
                 render();
                 return [cardLight, cardDark,
                         document.getElementById('strip-light'),
                         document.getElementById('strip-dark')].map(
                   c => c.toDataURL('image/png'));
               })""",
            [f["t"] for f in chunk],
        )
        for tuple_ in data:
            for key, uri in zip(keys, tuple_):
                raw = base64.b64decode(uri.split(",", 1)[1])
                streams[key].append(Image.open(io.BytesIO(raw)).convert("RGBA"))
        print(f"  captured {min(i + CAPTURE_CHUNK, len(frames))}/{len(frames)} "
              f"frames ({time.time() - started:.0f}s)")
    return streams


def downscale(frames):
    target = (round(frames[0].width * OUTPUT_SCALE / 2),
              round(frames[0].height * OUTPUT_SCALE / 2))
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
    blend into any page theme. Alpha is stepped to 4 levels — a full gradient
    dominates the lossless alpha plane's cost, while two levels (the GIF
    look) leaves hard, scratchy edges once the browser upscales the image."""
    rgb = frame.convert("RGB")                      # fully transparent px = black
    q = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
    q = q.point(lut)
    out = q.convert("RGB")
    out.putalpha(frame.getchannel("A").point(
        lambda a: min(255, round(a / 85) * 85)))
    return out


def dedupe(frames, durations_ms):
    """Collapse runs of identical frames into one frame with a longer
    duration — the artist caption moves sub-pixel per tick, so roughly a
    third of its frames carry no change at all."""
    out_f, out_d = [], []
    for f, d in zip(frames, durations_ms):
        if out_f and ImageChops.difference(
                f.convert("RGBA"), out_f[-1].convert("RGBA")).getbbox() is None:
            out_d[-1] += d
        else:
            out_f.append(f)
            out_d.append(d)
    return out_f, out_d


def encode_webp(frames, durations_ms, dest):
    durations = [round(d) for d in durations_ms]
    frames[0].save(
        dest, format="WEBP", save_all=True, append_images=frames[1:],
        duration=durations, loop=0,
        lossless=True, method=6, kmin=0, kmax=0,
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
        streams = grab_frames(page, frames)
        browser.close()

    delays_cs = [f["delayCs"] for f in frames]
    durations_ms = [round(cs * 10) for cs in delays_cs]
    assets = ROOT / "assets"
    workdir = Path(tempfile.mkdtemp(prefix="player-frames-"))
    try:
        card_l = downscale(streams["cardL"])
        card_d = downscale(streams["cardD"])
        strip_l = downscale(streams["stripL"])
        strip_d = downscale(streams["stripD"])

        for theme, card in (("light", card_l), ("dark", card_d)):
            dest = assets / f"player-{theme}.webp"
            palette, lut = build_palette(card)
            quantized = [quantize_frame(f, palette, lut) for f in card]
            size = encode_webp(quantized, durations_ms, dest)
            print(f"wrote {dest.name} ({size / 1024:.0f} KB, {len(quantized)} frames)")

        for theme, strip_frames in (("light", strip_l), ("dark", strip_d)):
            frames_s, durs_s = dedupe(strip_frames, durations_ms)
            dest = assets / f"control-{theme}.webp"
            palette, lut = build_palette(frames_s)
            quantized = [quantize_frame(f, palette, lut) for f in frames_s]
            size = encode_webp(quantized, durs_s, dest)
            print(f"wrote {dest.name} ({size / 1024:.0f} KB, {len(quantized)} frames)")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
