"""Fetch song metadata + timed lyrics + cover art into player config.

Turns a platform song URL into what build.py / preview.py consume:
  --config PATH   config.json written here (default: config.json)
  --cover PATH    album art written here (default: the path in --config's cover)

Supported: QQ Music (y.qq.com), NetEase Cloud Music (music.163.com).
Both are unauthenticated public endpoints; the lyric source is line-level
LRC, which is exactly what the animated card's sliding window needs.

Usage:
  python fetch_song.py https://y.qq.com/n/ryqq_v2/songDetail/000D12Rr2pTCxT
  python fetch_song.py <url> --config config.json --cover cover.jpg
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

WIDGET = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def http_json(url: str, referer: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer,
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_download(url: str, dest: Path, referer: str = ""):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp, \
            open(dest, "wb") as f:
        f.write(resp.read())


def fmt_clock(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


def parse_seconds(text: str) -> float:
    parts = [float(p) for p in text.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


# ---- QQ Music ----

def fetch_qq(mid: str) -> dict:
    detail = http_json(
        "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg"
        f"?songmid={mid}&format=json", "https://y.qq.com/")
    song = detail["data"][0]
    lyric = http_json(
        "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
        f"?songmid={mid}&g_tk=5381&format=json&nobase64=1", "https://y.qq.com/")
    return {
        "title": song["name"],
        "artist": " · ".join(s["name"] for s in song.get("singer", [])),
        "duration_s": float(song["interval"]),
        "lrc": lyric.get("lyric", ""),
        "cover_url": ("https://y.gtimg.cn/music/photo_new/T002R500x500M000"
                      + song["album"]["mid"] + ".jpg"),
        "cover_referer": "https://y.qq.com/",
    }


# ---- NetEase Cloud Music ----

def fetch_netease(song_id: str) -> dict:
    detail = http_json(
        f"https://music.163.com/api/song/detail/?id={song_id}"
        f"&ids=%5B{song_id}%5D", "https://music.163.com")
    song = detail["songs"][0]
    lyric = http_json(
        f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1",
        "https://music.163.com")
    cover = song["album"]["picUrl"] + "?param=500x500"
    return {
        "title": song["name"],
        "artist": " · ".join(a["name"] for a in song.get("artists", [])),
        "duration_s": song["duration"] / 1000.0,
        "lrc": lyric.get("lrc", {}).get("lyric", ""),
        "cover_url": cover,
        "cover_referer": "https://music.163.com",
    }


# ---- LRC timeline ----

CREDIT_RE = re.compile(
    r"作\s?[词曲编]|Lyrics?\s*by|Composed?\s*by|Arranged?\s*by|"
    r"Producer|混音|母带|录音|监制|纯音乐", re.IGNORECASE)
TIME_TAG = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(lrc_text: str, title: str = "", artist: str = "") -> list:
    def norm(s: str) -> str:
        return re.sub(r"[\s\-—·/（）()：:，,。.*]+", "", s or "").lower()

    header_keys = [norm(title)[:15]] if norm(title) else []
    header_keys += [norm(part) for part in re.split(r"[·/]", artist)
                    if len(norm(part)) > 2]
    lines = []
    offset_ms = 0.0
    for raw in lrc_text.splitlines():
        meta = re.match(r"^\s*\[offset:\s*(-?\d+)\s*\]", raw, re.IGNORECASE)
        if meta:
            offset_ms = float(meta.group(1))
    for raw in lrc_text.splitlines():
        text = TIME_TAG.sub("", raw).strip()
        if not text or text.startswith("["):
            continue                                    # header/meta tags
        if CREDIT_RE.search(text):
            continue
        stamps = list(TIME_TAG.finditer(raw))
        first_t = (int(stamps[0].group(1)) * 60 + int(stamps[0].group(2))
                   if stamps else 0.0)
        if first_t < 15 and any(k and k in norm(text) for k in header_keys):
            continue                                    # song title / artist banner
        for stamp in stamps:
            minutes, seconds, frac = stamp.groups()
            t = int(minutes) * 60 + int(seconds) + float(frac or 0) / 10 ** len(frac or "")
            lines.append({"t": round(max(0.0, t - offset_ms / 1000), 2),
                          "text": text})
    lines.sort(key=lambda x: x["t"])
    cleaned = []
    for line in lines:                                  # drop repeated stamps
        if cleaned and abs(cleaned[-1]["t"] - line["t"]) < 0.01 \
                and cleaned[-1]["text"] == line["text"]:
            continue
        cleaned.append(line)
    return cleaned


# ---- entry ----

def detect_platform(url: str):
    m = re.search(r"y\.qq\.com/(?:n/)?(?:ryqq_v?2?/)?songDetail/([0-9A-Za-z]+)", url)
    if m:
        return "qq", m.group(1)
    m = re.search(r"music\.163\.com/(?:#/)?song\?id=(\d+)", url)
    if m:
        return "netease", m.group(1)
    sys.exit(f"unsupported song url: {url}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--config", default=str(WIDGET / "config.json"))
    ap.add_argument("--cover", default=None,
                    help="album art destination (default: <config dir>/cover.jpg)")
    ap.add_argument("--start", default=None, metavar="M:SS",
                    help="loop open time (default: 1s before the first lyric line)")
    ap.add_argument("--end", default=None, metavar="M:SS",
                    help="loop close time (default: start + 60s, clamped to the song)")
    args = ap.parse_args()

    platform, song_id = detect_platform(args.url)
    fetcher = {"qq": fetch_qq, "netease": fetch_netease}[platform]
    info = fetcher(song_id)

    timeline = parse_lrc(info["lrc"], info["title"], info["artist"])
    if not timeline:
        sys.exit("no usable timed lyrics — the card needs at least one line")

    start = parse_seconds(args.start) if args.start else \
        max(0.0, timeline[0]["t"] - 1.0)            # open on the first line
    end = parse_seconds(args.end) if args.end else \
        min(start + 60.0, info["duration_s"])
    if not (0.0 <= start < end <= info["duration_s"] + 0.05):
        sys.exit(f"invalid interval {fmt_clock(start)}–{fmt_clock(end)} "
                 f"for a {fmt_clock(info['duration_s'])} song")

    config_path = Path(args.config)
    cover_path = Path(args.cover) if args.cover else config_path.parent / "cover.jpg"
    http_download(info["cover_url"], cover_path, info["cover_referer"])

    old = {}
    if config_path.exists():
        old = json.loads(config_path.read_text(encoding="utf-8"))
    cfg = {
        "title": info["title"],
        "artist": info["artist"],
        "lyrics": [line["text"] for line in timeline[:3]],
        "lyrics_timeline": [{"t": fmt_clock(line["t"]), "text": line["text"]}
                            for line in timeline],
        "elapsed": fmt_clock(start),
        "loop_end": fmt_clock(end),
        "loop_seconds": int(round(end - start)),
        "duration": fmt_clock(info["duration_s"]),
        "liked": old.get("liked", True),
        "cover": os.path.relpath(cover_path, config_path.parent).replace("\\\\", "/"),
    }
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"[{platform}] {info['title']} — {info['artist']}")
    print(f"  interval {cfg['elapsed']}–{cfg['loop_end']} of {cfg['duration']}, "
          f"{len(timeline)} lyric lines -> {config_path.name} + {cover_path.name}")


if __name__ == "__main__":
    main()
