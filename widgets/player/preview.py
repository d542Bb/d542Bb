"""Generate preview.html — the live, frame-exact preview of the player card.

The page is the single render source for the animated card: it redraws the
exact scene state for any timestamp via ?t=<seconds>, which is what the GIF
pipeline will screenshot frame by frame. Live mode plays the loop locally.

Inputs
  config.json                 song info (+ optional lyrics_timeline)
  cover.jpg                   album artwork (or the path set in config)
  qq-player-icons.png         2x icon sheet
  preview_template.html       page skeleton with a __PREVIEW_DATA__ slot

Output
  preview.html                self-contained page (images inlined as data URIs)

Usage: python widgets/player/preview.py [path/to/config.json]
"""

import base64
import json
import sys
from pathlib import Path

WIDGET = Path(__file__).resolve().parent


def parse_seconds(text: str) -> float:
    parts = [float(p) for p in text.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def compute_loop(cfg: dict) -> float:
    """Loop length in seconds. `loop_end` (m:ss) marks the interval freely;
    otherwise `loop_seconds` (default 60) runs from `elapsed`."""
    start = parse_seconds(cfg["elapsed"])
    if cfg.get("loop_end"):
        end = min(parse_seconds(cfg["loop_end"]), parse_seconds(cfg["duration"]))
        if end <= start:
            raise SystemExit(
                f"loop_end {cfg['loop_end']} must be after elapsed {cfg['elapsed']}")
        return max(5.0, end - start)
    return float(cfg.get("loop_seconds", 60))


def build_timeline(cfg: dict) -> list:
    """Lyric lines with start times. Uses lyrics_timeline when present,
    otherwise spreads the plain lyrics[] evenly from elapsed to the end."""
    if cfg.get("lyrics_timeline"):
        return [
            {"t": parse_seconds(item["t"]), "text": item["text"]}
            for item in cfg["lyrics_timeline"]
        ]
    start = parse_seconds(cfg["elapsed"])
    end = parse_seconds(cfg["duration"])
    lyrics = cfg.get("lyrics", [])
    if not lyrics:
        return []
    step = (end - start) / len(lyrics)
    return [
        {"t": start + i * step, "text": text}
        for i, text in enumerate(lyrics)
    ]


def data_uri(path: Path) -> str:
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp",
    }[path.suffix.lower()]
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_html(config_path: Path) -> str:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    loop = compute_loop(cfg)
    data = {
        "title": cfg["title"],
        "artist": cfg["artist"],
        "elapsed": cfg["elapsed"],
        "duration": cfg["duration"],
        "liked": bool(cfg.get("liked")),
        "loop": loop,
        "timeline": build_timeline(cfg),
        "cover": data_uri(WIDGET / cfg.get("cover", "cover.jpg")),
        "sprite": data_uri(WIDGET / "qq-player-icons.png"),
    }
    template = (WIDGET / "preview_template.html").read_text(encoding="utf-8")
    html = template.replace(
        "__PREVIEW_DATA__", json.dumps(data, ensure_ascii=False)
    )
    out = WIDGET / "preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out.relative_to(WIDGET.parents[1])} (loop {loop:g}s, "
          f"{len(data['timeline'])} lyric lines)")
    return out


def main():
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else WIDGET / "config.json"
    build_html(config_path)


if __name__ == "__main__":
    main()
