# Profile music player

A QQ-Music-style "now playing" card with a collapsible easter egg. The card and
control strip are static PNGs generated from a small config, so they work inside
GitHub's sanitized Markdown (no CSS or JS).

One of the widgets in this template — see [../README.md](../README.md) for the
big picture.

<picture><source media="(prefers-color-scheme: dark)" srcset="../assets/player-dark.png"><img src="../assets/player-light.png" width="599" alt="player card"></picture>
<br>
<picture><source media="(prefers-color-scheme: dark)" srcset="../assets/control-bar-dark.png"><img src="../assets/control-bar-light.png" width="577" alt="control bar"></picture>

## Use it

Follow the [quick start](../README.md#quick-start) in the template guide, then:

1. Edit [`config.json`](config.json) with your song.
2. Replace [`cover.jpg`](cover.jpg) with your album art (square image).
3. Edit the top of the root [`README.md`](../../README.md) — intro lines and
   the hidden source-only comment in the `<details>` block.

Push and the **Build profile artwork** workflow regenerates the PNGs in
`assets/` and commits them automatically.

## Config fields

| Field | Meaning |
| --- | --- |
| `title` | Song title; truncated with an ellipsis if too wide. |
| `artist` | Caption centred under the cover. |
| `lyrics` | Up to three lines: current, then two fading lines. |
| `lyrics_timeline` | Optional. `[{ "t": "m:ss", "text": ... }]` start times per line; drives the animated preview's highlight and slide. Falls back to spreading `lyrics` evenly from `elapsed` to the end. |
| `elapsed` / `duration` | `m:ss` times; the progress bar fills to `elapsed / duration`. |
| `liked` | `true` shows a filled red heart, `false` an outline. |
| `cover` | Path to the album art, relative to this folder. |
| `loop_seconds` | Optional. Length of the animated preview loop (default 60). |

## Build locally

```bash
pip install Pillow
python widgets/player/build.py
```

Outputs `assets/player-{light,dark}.png` and `assets/control-bar-{light,dark}.png`.
The build is deterministic: the same config and inputs produce identical files.

## Fetch from a streaming platform

`fetch_song.py` rewrites the config from a song URL — no login needed:

```bash
python widgets/player/fetch_song.py https://y.qq.com/n/ryqq_v2/songDetail/<mid>
python widgets/player/fetch_song.py https://music.163.com/song?id=<id>
```

It pulls title / artist / duration, the line-level LRC timeline (credits and
title-banner lines filtered out) and the 500x500 album art, then writes
`config.json` + `cover.jpg` (override with `--config` / `--cover`). The
workflow can call this before building to turn "paste a link" into a full
automated render.

## Animated preview (GIF frame source)

`preview.py` generates `preview.html` (gitignored) from the template, config,
cover and icon sheet — everything inlined, so the file opens directly in a
browser. The page draws the card on canvases with the exact geometry of
`build.py`, and the scene is a pure function of the render time:

- Live mode plays the loop for eyeballing; controls: play/pause, seek,
  loop length, light and dark side by side.
- `?t=<seconds>` freezes the exact frame at that time — this is what the GIF
  pipeline screenshots frame by frame (headless Chromium in the workflow).
  Capturers wait for `window.__previewReady`.
- The overlay visualizes the per-element frame schedule the GIF encoder will
  follow: title band on every base tick (red), progress + clock at 1 Hz (blue,
  state quantized to whole seconds), lyrics only during the 0.3 s slide after
  a line change (green); amber is the actual per-frame patch (the union).
  “按调度表逐帧实测” draws every scheduled frame and pixel-diffs it against
  the previous one, verifying the real changes stay inside the analytic patch.

Note for CI: headless Chromium throttles `requestAnimationFrame` in unseen
windows, so always capture via `?t=` frames, never by letting live mode run.
Install `fonts-liberation` on the runner so text metrics match.

## How it works

- `build.py` renders at 2x and downsamples for crisp text. Layout, colours
  and the icon sprite live in the script; only the song info comes from the config.
- Light and dark variants are selected with `<picture>` + `prefers-color-scheme`.
  Both `src` and `srcset` use repo-relative paths, so the template is portable.
- The control strip is the `<details>` summary, so GitHub's native disclosure
  triangle lines up with the first transport icon and acts as the play button.

## Assets and licensing

- `fonts/LiberationSans-Regular.ttf` — bundled so the build runs anywhere (including
  Linux CI). SIL Open Font License 1.1; see [`fonts/LICENSE.txt`](fonts/LICENSE.txt).
- `qq-player-icons.png` — icon sprite extracted from the QQ Music player.
- `cover.jpg` — sample album art; replace it with your own.