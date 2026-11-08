# Profile widgets

Reusable building blocks for a GitHub profile README. Each folder in `widgets/`
is self-contained: its config, build script, static assets and docs live inside
it, and running its `build.py` regenerates the images it owns in `assets/`.

| Widget | Generates | Docs |
| --- | --- | --- |
| [`player/`](player/) | `assets/player-{light,dark}.png`, `assets/control-bar-{light,dark}.png` | [player/README.md](player/README.md) |
| [`stickers/`](stickers/) | `assets/stickers.png` | [stickers/README.md](stickers/README.md) |

- **Filenames in `assets/` are the contract.** The profile README only ever
  references generated images by name, so widget internals can be reorganised
  freely without ever touching the README. (Hand-placed personal images, like
  an easter egg, live in `assets/` too.)
- Don't need a widget? Delete its folder — `.github/workflows/build-widgets.yml`
  builds whatever `widgets/*/build.py` files remain.
- Adding your own widget: create `widgets/<name>/build.py` that reads
  `widgets/<name>/config.json` and writes PNGs into `assets/`. No workflow
  changes needed.

Build everything locally:

```bash
pip install Pillow
python widgets/build_all.py
```
