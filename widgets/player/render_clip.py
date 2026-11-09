"""Render the animated player card as lossless animated WebP assets.

Pipeline: rebuild preview.html from the config, open it in headless
Chromium, walk the per-frame schedule the page computed, pull frames off
the canvases, and encode:

  player-left-{theme}.webp    animated card half (title/lyrics/progress)
  player-cover.png            static transparent album-art half
  control-left-{theme}.png    static transport + volume strip
  control-right-{theme}.webp  artist caption — a slow marquee anchored to
                              the album-art axis when the name is long,
                              a single static frame when it is short

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
LEFT_W = 400                     # animated card half, css px; card is 599
STRIP_SPLIT = 400                # animated caption half, css px; strip is 577
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
    """Pull every scheduled frame off the four animated canvases as PIL
    images, plus one static grab of the transport-strip left blocks."""
    started = time.time()
    streams = {"cardL": [], "cardD": [], "stripRL": [], "stripRD": []}
    keys = ("cardL", "cardD", "stripRL", "stripRD")
    for i in range(0, len(frames), CAPTURE_CHUNK):
        chunk = frames[i:i + CAPTURE_CHUNK]
        data = page.evaluate(
            """(ts) => ts.map(t => {
                 state.t = t;
                 render();
                 return [cardLight, cardDark,
                         document.getElementById('stripr-light'),
                         document.getElementById('stripr-dark')].map(
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
    # transport strip left blocks: static, one grab each
    streams["stripLL"] = [
        Image.open(io.BytesIO(base64.b64decode(
            u.split(",", 1)[1]))).convert("RGBA")
        for u in page.evaluate(
            """() => [document.getElementById('strip-light'),
                      document.getElementById('strip-dark')].map(
                c => c.toDataURL('image/png'))""")
    ]
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
        streams = grab_frames(page, frames)
        browser.close()

    delays_cs = [f["delayCs"] for f in frames]
    durations_ms = [round(cs * 10) for cs in delays_cs]
    assets = ROOT / "assets"
    workdir = Path(tempfile.mkdtemp(prefix="player-frames-"))
    try:
        # the card canvases are full-width (2x of 599 css); crop the animated
        # left half (800 of 1198) before downscaling
        card_l = downscale([f.crop((0, 0, 800, f.height)) for f in streams["cardL"]])
        card_d = downscale([f.crop((0, 0, 800, f.height)) for f in streams["cardD"]])
        strip_rl = downscale(streams["stripRL"])
        strip_rd = downscale(streams["stripRD"])
        strip_ll = downscale(streams["stripLL"])
        split_x = round(LEFT_W * OUTPUT_SCALE)          # 600 at 1.5x

        # static cover half (identical in both themes): the right slice of
        # the full card (2x 800..1198 = css 400..599)
        cover_full = streams["cardL"][0].crop(
            (800, 0, streams["cardL"][0].width, streams["cardL"][0].height))
        cover = cover_full.resize(
            (round(cover_full.width * OUTPUT_SCALE / 2),
             round(cover_full.height * OUTPUT_SCALE / 2)), Image.LANCZOS)
        cover_path = assets / "player-cover.png"
        cover.save(cover_path, optimize=True)
        print(f"wrote player-cover.png ({cover_path.stat().st_size / 1024:.0f} KB)")

        for theme, card in (("light", card_l), ("dark", card_d)):
            dest = assets / f"player-left-{theme}.webp"
            palette, lut = build_palette(card)
            quantized = [quantize_frame(f, palette, lut) for f in card]
            size = encode_webp(quantized, durations_ms, dest)
            print(f"wrote {dest.name} ({size / 1024:.0f} KB, {len(quantized)} frames)")

        for theme, strip_frames, strip_left in (
                ("light", strip_rl, strip_ll[0]), ("dark", strip_rd, strip_ll[1])):
            # transport strip left block canvas: transport + volume (static);
            # right block canvas: artist caption (animated only when long)
            strip_left.save(assets / f"control-left-{theme}.png", optimize=True)
            frames_r, durs_r = dedupe(strip_frames, durations_ms)
            scrolling = len(frames_r) > 1
            dest = assets / f"control-right-{theme}.webp"
            palette, lut = build_palette(frames_r)
            quantized = [quantize_frame(f, palette, lut) for f in frames_r]
            size = encode_webp(quantized, durs_r, dest)
            mode = "marquee" if scrolling else "static"
            print(f"wrote {dest.name} ({size / 1024:.0f} KB, {len(quantized)} frames, {mode})")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
