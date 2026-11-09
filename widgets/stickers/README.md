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

<picture><img src="../../assets/stickers.png" width="330" alt="sticker board"></picture>

## Use it on your profile

The board is responsive: one PNG per screen band, swapped by a `<picture>`
stack. **Your whole responsive plan lives in `config.json`** — the tiers are
its `variants`, each designed for one canvas width (the hole beside your text
at some window size); `target` is the desktop-ceiling board. Then:

```bash
python widgets/stickers/stack.py
```

prints the `<picture>` markup with all viewport breakpoints derived from your
tiers (it follows GitHub's profile column curve, including the sidebar squeeze
band) — paste it **before** the text the board should sit beside. Sample
tiers in this config, tuned for our text:

| variant | canvas | shape |
| --- | --- | --- |
| `phone` | 130 | portrait pile |
| `slim` | 145 | portrait pile |
| `compact` | 172 | near-square |
| `wide` | 195 | wide sheet |
| `target` | 282 (ceiling) | wide sheet |

Pick your own tier widths by where your text block's height steps (it changes
in jumps as lines wrap/unwrap — dense tiers where it steps hard, sparse where
it is flat; a good rule is adjacent tiers' aspect ratio within ~1.25×). The
pieces to tune:

- **`share`** — the board's share of the column at every screen size (a fixed
  pixel width would crush the text on phones). The stack generator turns it
  into the `width` percentage.
- **Each variant's `width`** — the canvas it is designed for; the frame's
  height should match your text height at that width (measure once, or build,
  look and adjust; the motion preview in the repo wiki shows the whole axis).
- **`max_sheet_px`** caps the saved PNG's raw pixel width. GitHub sizes its
  content-width table from an image's raw pixels, so a full 2× sheet can
  inflate the table and leave a hole beside your widest row. Keep the cap
  under your widest row's content width minus 20px (the padding GitHub puts
  on README images — that padding is also the gap between text and stickers,
  so the PNG needs none baked in), while staying ~2× the display box so
  retina stays sharp.
- Opaque sources (photos, screenshots) also work — they are automatically
  rounded and framed like a die-cut sticker.

## Config fields

Edit [`config.json`](config.json), drop source images into [`stickers/`](stickers/),
then push — the **Build profile artwork** action regenerates the board.

| Field | Meaning |
| --- | --- |
| `share` | The board's share of the column at every screen size; the stack generator turns it into the README's `width` percentage. |
| `target.width` / `height` | Display box of the desktop-ceiling board, in CSS px. The build pads the PNG to exactly this aspect; the README's percentage scales it. |
| `max_sheet_px` | Cap on the saved PNG's raw pixel width (default 578). Keep it under your widest row's content width minus 20px, or the table may inflate; see "Use it on your profile". |
| `stickers[].src` | Image path, relative to this folder. |
| `stickers[].size` | On-screen width in px on the desktop board; height scales to match. Unspecified stickers fall back to `defaults.size`. |
| `stickers[].x` / `y` | Centre position of the sticker on the desktop board. |
| `stickers[].rotate` | Tilt in degrees (counter-clockwise), or `"random"` for a stable per-sticker random tilt (seeded by the file name, so builds stay reproducible). Subtle values like ±8–15 look best. |
| `stickers[].hero` | `true` on one sticker: it gets the largest size share when suggesting and is drawn on top of the pile. |
| `stickers[].pinned` | `true` keeps this sticker's placement when the suggester re-runs. |
| `stickers[].border` | White outline width in px. Default 9; `0` disables. |
| `stickers[].shadow` | `false` disables the drop shadow (on by default). |
| `stickers[].alpha_threshold` | Alpha below this counts as background. Default 250 (set in `defaults`); `0` keeps every pixel as-is. |
| `stickers[].solidify` | Fine-tune the solidify pass: `{ "min_keep": 0.04, "fill_holes": true, "close": 2 }`. |
| `stickers[].harmonize` / `material` | `false` opts one sticker out of colour harmonisation / the enamel finish. |
| `variants.<name>` | One tier per screen band — a board designed for one canvas width (the hole beside the text). Fields: `width` (the canvas it is designed for), `height` (frame height, aim at your text height there), `output` (PNG file name under `assets/`), optional `layout` (a size/x/y/rotate list; generated automatically when absent). The stack generator turns the tiers into README markup. |

Shared knobs live in the top-level `defaults` object and apply to every
sticker unless overridden per sticker — including `size` (a shared default
on-screen width) and the render toggles below.

## Suggesting a layout

After adding or removing stickers or changing a frame, let the tool propose
sizes and positions:

```bash
python widgets/stickers/suggest.py          # desktop board -> stickers[]
python widgets/stickers/suggest.py narrow   # a variant -> variants.narrow.layout
```

It splits an area budget across the stickers (the `hero` gets the largest
share), scatters them on a frame-shaped ellipse, relaxes the pile until
neighbours overlap by roughly 10–30% of the smaller one, then stretches the
pile to fill the frame — a lively sheet with no dead corners. Suggested values
are written back into `config.json`; tweak them by hand afterwards, and mark a
sticker `"pinned": true` to keep it exactly where you set it.

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
