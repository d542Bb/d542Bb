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
| `elapsed` / `duration` | `m:ss` times; the progress bar fills to `elapsed / duration`. |
| `liked` | `true` shows a filled red heart, `false` an outline. |
| `cover` | Path to the album art, relative to this folder. |

## Build locally

```bash
pip install Pillow
python widgets/player/build.py
```

Outputs `assets/player-{light,dark}.png` and `assets/control-bar-{light,dark}.png`.
The build is deterministic: the same config and inputs produce identical files.

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