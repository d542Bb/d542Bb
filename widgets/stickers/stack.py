"""Emit the README's <picture> switching stack from config.json.

Each variant in config.json is designed for one canvas width (the hole beside
the text at some window size); `target` is the desktop-ceiling board. This
script maps every viewport width to the tier whose canvas matches the hole
there, finds the maximal viewport bands, and prints the picture markup to
paste into the README — breakpoints always in sync with the config.

Usage: python widgets/stickers/stack.py
"""

import json
from pathlib import Path

WIDGET = Path(__file__).resolve().parent
V_MIN, V_MAX = 320, 2400


def container(v):
    """GitHub profile page: content column width vs viewport (probe-measured).

    The sidebar collapses below ~770px; between ~770-1011 it squeezes the
    column; above that the table hits its content-width ceiling (599px).
    """
    if v <= 723:
        return v - 124
    if v <= 770:
        return 599
    if v <= 1011:
        return v - 412
    return 599


def main():
    cfg = json.loads((WIDGET / "config.json").read_text(encoding="utf-8"))
    share = cfg.get("share", 0.47)
    target_w = cfg["target"]["width"]
    tiers = sorted(
        [(name, spec["width"], spec.get("output", f"stickers-{name}.png"))
         for name, spec in cfg.get("variants", {}).items()],
        key=lambda t: t[1],
    )
    names = [t[0] for t in tiers] + ["main"]
    widths = [t[1] for t in tiers] + [target_w]
    outs = {t[0]: t[2] for t in tiers}
    boundaries = [(widths[i] + widths[i + 1]) / 2 for i in range(len(widths) - 1)]

    def tier_at(v):
        slot = share * container(v)
        idx = 0
        for i, b in enumerate(boundaries):
            if slot >= b:
                idx = i + 1
        return idx

    bands = []
    prev = None
    for v in range(V_MIN, V_MAX + 1):
        idx = tier_at(v)
        if idx != prev:
            if prev is not None:
                bands[-1]["end"] = v - 1
            bands.append({"idx": idx, "start": v})
            prev = idx
    bands[-1]["end"] = V_MAX

    def src_for(name):
        return "assets/stickers.png" if name == "main" else outs[name]

    lines = ["<picture>"]
    for i, b in enumerate(bands[:-1]):
        media = f"(max-width: {b['end']}px)" if i == 0 \
            else f'(min-width: {b["start"]}px) and (max-width: {b["end"]}px)'
        lines.append(f'  <source media="{media}" srcset="{src_for(names[b["idx"]])}">')
    lines.append(f'  <img src="assets/stickers.png" width="{round(share * 100)}%" '
                 f'align="right" alt="">')
    lines.append("</picture>")
    print("\n".join(lines))
    print(f"\n{len(bands) - 1} switch points across {len(bands)} bands; "
          f"paste the block above into the README where the board should sit.")


if __name__ == "__main__":
    main()
