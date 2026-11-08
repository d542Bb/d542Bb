# Sticker board

A transparent canvas that composes your images into a Duolingo-style sticker
board, no matter what you feed it. Every image runs through one pipeline:
soft backgrounds are cut away and the silhouette solidified into a die-cut,
colours are harmonised toward a shared palette, then the sticker gets a white
outline, an enamel finish (bevelled rim, soft sheen, fine grain), a tilt and a
soft drop shadow. The result is a single PNG you can place anywhere in the
README — right of your intro text, left, or on its own line. The background is
transparent, so the same image works in light and dark mode.

Preview (sample stickers — replace them with your own):

<picture><img src="../../assets/stickers.png" width="300" alt="sticker board"></picture>

## Use it on your profile

Reference the generated image where you want the board, **before** the text it
should sit beside. Check the build log for the actual pixel size of the PNG
(it auto-fits the stickers) and set `width` accordingly — around the canvas
size from the config keeps the design at its intended scale:

Right of the text (text wraps on its left):

```html
<img src="assets/stickers.png" align="right" width="330" alt="">
```

Left of the text:

```html
<img src="assets/stickers.png" align="left" width="330" alt="">
```

Tips:

- Keep `width` at or below ~40% of the content column (≈300px on desktop);
  on phones the column is narrow and the text needs room to wrap.
- The floated image occupies vertical space too: keep the canvas height close
  to the height of the text block beside it, otherwise the next element (e.g.
  the player card) gets pushed further down.
- Transparent PNGs look best. Opaque images (photos, screenshots) also work —
  they are automatically rounded and framed like a die-cut sticker.

## Config fields

Edit [`config.json`](config.json), drop source images into [`stickers/`](stickers/),
then push — the **Build profile artwork** action regenerates the board.

| Field | Meaning |
| --- | --- |
| `canvas.width` / `canvas.height` | Coordinate frame for sticker positions. The saved PNG auto-expands to fit every sticker plus its shadow — it never hard-clips (set `"fit": false` to clip at this frame instead). |
| `stickers[].src` | Image path, relative to this folder. |
| `stickers[].size` | On-screen width in px; height scales to match. Unspecified stickers fall back to `defaults.size`. |
| `stickers[].x` / `y` | Centre position of the sticker on the canvas. |
| `stickers[].rotate` | Tilt in degrees (counter-clockwise), or `"random"` for a stable per-sticker random tilt (seeded by the file name, so builds stay reproducible). Subtle values like ±8–15 look best. |
| `stickers[].border` | White outline width in px. Default 9; `0` disables. |
| `stickers[].shadow` | `false` disables the drop shadow (on by default). |
| `stickers[].alpha_threshold` | Alpha below this counts as background. Default 250 (set in `defaults`); `0` keeps every pixel as-is. |
| `stickers[].solidify` | Fine-tune the solidify pass: `{ "min_keep": 0.04, "fill_holes": true, "close": 2 }`. |
| `stickers[].harmonize` / `material` | `false` opts one sticker out of colour harmonisation / the enamel finish. |

Shared knobs live in the top-level `defaults` object and apply to every
sticker unless overridden per sticker — including `size` (a shared default
on-screen width) and the render toggles below.

## Semi-transparent sources

The board needs every sticker to be one solid silhouette. Sources with soft or
semi-transparent backgrounds (glows, speed lines, faint strokes) are handled
automatically:

1. Pixels whose alpha is below `alpha_threshold` are treated as background.
2. Connected pieces much smaller than the main shape are dropped, and enclosed
   holes are filled — what remains is one solid die-cut shape.
3. Faint leftovers near the edge are folded into the white frame instead of
   printing as grey smudges.

If the cut eats into real artwork, lower `alpha_threshold` for that sticker;
if background clutter survives, raise it.

## Build locally

```bash
pip install Pillow
python widgets/stickers/build.py
```

The build is deterministic: the same config and inputs produce identical files.
