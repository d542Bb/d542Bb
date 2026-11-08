# GitHub profile widgets

A GitHub profile README that is actually alive: a QQ-Music-style **"now playing"
player** and a **Duolingo-style sticker board**, both rendered to static PNGs by
GitHub Actions. No JavaScript, no external services — everything works inside
GitHub's sanitized Markdown, in light and dark mode.

Rendered by this very repo (see it live on [the profile](https://github.com/d542Bb)):

| | |
| --- | --- |
| ![*sticker board*](../assets/stickers.png) | ![*music player*](../assets/player-light.png) |

## Quick start

1. Click **Use this template** and name the new repo `<your-username>/<your-username>`
   — a repository matching your username renders its README on your profile.
2. Trim: delete the folder of any widget you don't want (each is self-contained).
3. Personalise: edit each widget's `config.json`, replace its sample images,
   follow its README for the supported knobs.
4. Edit the root [`README.md`](../README.md) — that file is your profile, it is
   yours. The widgets only ever feed it images by file name.
5. Push. The **Build profile artwork** workflow regenerates the PNGs in
   `assets/` and commits them automatically.

## The widgets

| Widget | Generates | Docs |
| --- | --- | --- |
| [`player/`](player/) | `assets/player-{light,dark}.png`, `assets/control-bar-{light,dark}.png` | [player/README.md](player/README.md) |
| [`stickers/`](stickers/) | `assets/stickers.png` | [stickers/README.md](stickers/README.md) |

## How it is put together

- Every widget folder is self-contained: its `config.json`, `build.py`, static
  assets and docs live inside it.
- **Filenames in `assets/` are the contract.** The profile README only ever
  references generated images by name, so widget internals can be reorganised
  freely without touching the README. (Hand-placed personal images, like an
  easter egg, live in `assets/` too.)
- One workflow builds whatever `widgets/*/build.py` files exist — adding or
  removing a widget never touches YAML.
- Builds are deterministic: the same inputs produce byte-identical files, so
  the committing Action stays quiet until something actually changes.
- Everything renders at 2x and downsamples, for crisp text and clean outlines.

## Placing widgets in the README

Float an image beside your text and let it scale with the viewport:

```html
<img src="assets/stickers.png" align="right" width="40%" alt="">
```

- `width` in percent keeps the layout working on phones: 40% ≈ 330px on
  desktop, proportionally smaller on mobile where the column is narrow.
- A fixed pixel width (`width="330"`) looks the same on desktop but squeezes
  your text into a sliver on phones.
- The sticker board's canvas auto-expands to fit its content, so check the
  workflow log (or run it locally) for the actual pixel size when picking a %.
- Individual stickers inside the composed board can't carry links — if you
  need a clickable element, place a separate `<a href="..."><img ...></a>`.

## Adding your own widget

Create `widgets/<name>/build.py` that reads `widgets/<name>/config.json` and
writes PNGs into `assets/`. Nothing else to register — the workflow picks it
up on the next push.

## Build locally

```bash
pip install Pillow
python widgets/build_all.py
```

## Licensing

- The code is released under the [MIT license](../LICENSE).
- `player/fonts/` bundles Liberation Sans (SIL Open Font License 1.1).
- `player/qq-player-icons.png` was extracted from the QQ Music client for
  personal-profile use — replace it if you plan to redistribute the imagery.
- The sample images in `stickers/stickers/` are placeholders from various
  sources; replace them with your own.
